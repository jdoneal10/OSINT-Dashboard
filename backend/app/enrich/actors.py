"""Rule-based actor normalization v1: ACLED actor strings → canonical ``actors`` rows.

Rules, in order, for each raw actor string (ACLED actor1/actor2 and the ``;``-separated
associated actors):

1. Clean: drop every parenthetical (``(Mexico)``, ``(2018-)``), collapse whitespace.
2. Match the cleaned name against ``actor_aliases.alias_normalized`` (accent/case-insensitive).
3. If it has a ``Parent: Detail`` or ``Parent - Detail`` form, match each part; when one part
   matches a known actor, either link to it (the other part restates it, e.g. "CJNG: Jalisco
   New Generation Cartel") or, if the other part names a faction, link to a faction actor
   created under that parent.
4. Otherwise create a new actor typed from ACLED's inter category; the raw string becomes
   its alias and ACLED is cited.

Organizations and groups only (CLAUDE.md hard rule 3): ACLED's actor fields code groups,
and this step never creates person-level records. Roles mirror ACLED's dyad exactly
(``actor1``, ``actor2``, ``assoc_actor1``, ``assoc_actor2``) with no perpetrator/target claim.

Curated reference actors (``data/reference/actor_aliases.yaml``) win over actors this step
created: when both own an alias, the curated actor gets the link. A rebuild then deletes
ACLED-created actors left with no events, children or designations, so adding a cited entry
for a group ACLED codes separately moves its events onto the curated record.

Re-run everything from stored attributes with ``python -m app.enrich.actors --rebuild``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Actor, ActorAlias, Event, actor_events, designation_actors
from app.db.session import session_factory
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

ACLED_ROLES = ("actor1", "actor2", "assoc_actor1", "assoc_actor2")
_ROLE_FIELDS = {
    "actor1": ("actor1", "inter1"),
    "actor2": ("actor2", "inter2"),
    "assoc_actor1": ("assoc_actor_1", "inter1"),
    "assoc_actor2": ("assoc_actor_2", "inter2"),
}
_PARENS = re.compile(r"\([^)]*\)")
_SPLIT = re.compile(r"\s*:\s+|\s+-\s+")
_FACTION = re.compile(r"\b(faction|facci[oó]n|wing|cell|c[eé]lula)\b", re.IGNORECASE)

# ACLED inter categories (numeric legacy codes and current text labels) → actor_type.
_INTER_TYPES = {
    "1": "state",
    "state forces": "state",
    "2": "armed_group",
    "rebel group": "armed_group",
    "3": "armed_group",
    "political militia": "armed_group",
    "4": "armed_group",
    "identity militia": "armed_group",
    "5": "other",
    "rioters": "other",
    "6": "other",
    "protesters": "other",
    "7": "civilian",
    "civilians": "civilian",
    "8": "other",
    "external/other forces": "other",
}

ACLED_CITATION = {
    "title": "Actor name as coded in ACLED event data",
    "publisher": "ACLED (Armed Conflict Location & Event Data)",
    "url": "https://acleddata.com",
}
# Actors this step created cite only ACLED; reference actors cite their own public sources.
_ACLED_CREATED = Actor.sources[0]["publisher"].astext == ACLED_CITATION["publisher"]


def clean_name(raw: str) -> str:
    return " ".join(_PARENS.sub(" ", raw).split())


def actor_type_for(inter: str | None) -> str:
    return _INTER_TYPES.get((inter or "").strip().lower(), "other")


def split_actors(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize_alias(name)).strip("-")[:56] or "actor"


@dataclass
class ActorIndex:
    """In-memory alias index for one normalization pass."""

    session: Session
    by_alias: dict[str, int]
    slugs: set[str]
    names: set[str]

    @classmethod
    def load(cls, session: Session) -> ActorIndex:
        # ACLED-created owners first so a curated owner of the same alias overwrites them.
        rows_by_owner = session.execute(
            select(ActorAlias.alias_normalized, ActorAlias.actor_id)
            .join(Actor, Actor.id == ActorAlias.actor_id)
            .order_by(_ACLED_CREATED.is_(True).desc(), ActorAlias.actor_id)
        ).all()
        aliases = {key: actor_id for key, actor_id in rows_by_owner}
        rows = session.execute(select(Actor.slug, Actor.canonical_name)).all()
        return cls(
            session=session,
            by_alias=aliases,
            slugs={s for s, _ in rows},
            names={normalize_alias(n) for _, n in rows},
        )

    def match(self, name: str) -> int | None:
        key = normalize_alias(name)
        return self.by_alias.get(key) if key else None

    def _unique_slug(self, name: str) -> str:
        base = _slugify(name)
        slug, n = base, 2
        while slug in self.slugs:
            slug, n = f"{base}-{n}", n + 1
        self.slugs.add(slug)
        return slug

    def create(self, name: str, raw: str, actor_type: str, parent_id: int | None = None) -> int:
        citation = ACLED_CITATION | {"accessed": dt.date.today().isoformat()}  # noqa: DTZ011
        canonical = name
        n = 2
        while normalize_alias(canonical) in self.names:
            canonical, n = f"{name} ({n})", n + 1
        actor = Actor(
            slug=self._unique_slug(name),
            canonical_name=canonical,
            actor_type=actor_type,
            parent_id=parent_id,
            country_iso3=None,
            sources=[citation],
        )
        self.session.add(actor)
        self.session.flush()
        self.names.add(normalize_alias(canonical))
        for alias in {name, raw}:
            key = normalize_alias(alias)
            if key and key not in self.by_alias:
                self.session.execute(
                    insert(ActorAlias)
                    .values(
                        actor_id=actor.id,
                        alias=alias,
                        alias_normalized=key,
                        sources=[citation],
                    )
                    .on_conflict_do_nothing()
                )
                self.by_alias[key] = actor.id
        return actor.id

    def resolve(self, raw: str, inter: str | None) -> int:
        name = clean_name(raw)
        if (hit := self.match(raw)) is not None or (hit := self.match(name)) is not None:
            return hit
        parts = [p for p in _SPLIT.split(name) if p]
        if len(parts) == 2:
            left, right = parts
            for known, other in ((left, right), (right, left)):
                parent = self.match(known)
                if parent is None:
                    continue
                if _FACTION.search(other):
                    faction = self.match(other)
                    if faction is None:
                        faction = self.create(other, raw, "faction", parent_id=parent)
                    self.by_alias[normalize_alias(name)] = faction
                    return faction
                self.by_alias[normalize_alias(name)] = parent  # e.g. "CJNG: Jalisco New ..."
                return parent
        return self.create(name, raw, actor_type_for(inter))


def link_events(session: Session, event_ids: Iterable[int], index: ActorIndex | None = None) -> int:
    """(Re)build ACLED-role ``actor_events`` rows for the given events. Returns links made."""
    ids = list(event_ids)
    if not ids:
        return 0
    index = index or ActorIndex.load(session)
    session.execute(
        delete(actor_events).where(
            actor_events.c.event_id.in_(ids), actor_events.c.role.in_(ACLED_ROLES)
        )
    )
    links: set[tuple[int, int, str]] = set()
    for event_id, attrs in session.execute(
        select(Event.id, Event.attributes).where(Event.id.in_(ids))
    ):
        for role, (field, inter_field) in _ROLE_FIELDS.items():
            for raw in split_actors(attrs.get(field)):
                links.add((index.resolve(raw, attrs.get(inter_field)), event_id, role))
    rows = [{"actor_id": a, "event_id": e, "role": r} for a, e, r in sorted(links)]
    # 3 bind parameters per row; stay well under Postgres's 65,535 limit.
    for start in range(0, len(rows), 10_000):
        session.execute(
            insert(actor_events).values(rows[start : start + 10_000]).on_conflict_do_nothing()
        )
    return len(links)


def prune_unlinked(session: Session) -> int:
    """Delete ACLED-created actors with no event links, child actors or designations."""
    child = Actor.__table__.alias("child")
    deleted = session.scalars(
        delete(Actor)
        .where(
            _ACLED_CREATED,
            ~exists().where(actor_events.c.actor_id == Actor.id),
            ~exists().where(child.c.parent_id == Actor.id),
            ~exists().where(designation_actors.c.actor_id == Actor.id),
        )
        .returning(Actor.id)
        .execution_options(synchronize_session=False)
    ).all()
    return len(deleted)


def rebuild(session: Session, batch: int = 2000) -> int:
    index = ActorIndex.load(session)
    total = 0
    ids = list(session.scalars(select(Event.id).order_by(Event.id)))
    for start in range(0, len(ids), batch):
        total += link_events(session, ids[start : start + batch], index)
    # Factions are deleted before an orphaned parent is seen as childless; loop to a fixpoint.
    while (pruned := prune_unlinked(session)) > 0:
        log.info("pruned %d ACLED-created actors with no remaining links", pruned)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.enrich.actors")
    parser.add_argument("--rebuild", action="store_true", help="relink every event")
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)
    if not args.rebuild:
        parser.error("nothing to do (use --rebuild)")
    with session_factory()() as session, session.begin():
        n = rebuild(session)
    log.info("relinked %d actor-event links", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
