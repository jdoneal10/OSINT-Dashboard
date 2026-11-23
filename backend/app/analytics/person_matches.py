"""Suggested person merges for the owner to review (ADR 0013 amendment 1).

Suggestions never merge anything. Names alone never make a confident suggestion unless they
are the same full name; a nickname needs a compatible name plus shared context. Everything
else is offered unticked. Pairs the owner marked "not the same person" are never suggested.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, PersonAttribute, PersonOrganization, event_documents
from app.enrich.identity import Identities
from app.enrich.person_guard import PLACEHOLDERS
from app.enrich.persons import alias_forms, name_key, name_words
from app.reference.normalize import normalize_alias

NEAR_DAYS = 3  # same place this many days apart is taken as possibly the same incident
CONTEXT_DAYS = 14  # reports this close together can support a shared nickname
TYPO_RATIO = 0.85  # "Irvin" / "Irving"

Strength = Literal["likely", "possible"]


@dataclass
class Profile:
    """One identity's comparable facts, over all of its linked records."""

    root: int
    names: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    name_forms: set[str] = field(default_factory=set)
    orgs: set[int] = field(default_factory=set)
    docs: set[int] = field(default_factory=set)
    reported: set[dt.date] = field(default_factory=set)
    places: set[tuple[str, dt.date]] = field(default_factory=set)

    def rank(self) -> tuple[int, int, int, int]:
        """Best display record first: fullest unmasked name, then most reported."""
        best = max((name_key(n) is not None, len(name_words(n))) for n in self.names)
        return (int(best[0]), best[1], len(self.docs), -self.root)


@dataclass(frozen=True)
class Match:
    strength: Strength
    reasons: tuple[str, ...]


@dataclass
class Candidate:
    person_id: int
    selected: bool
    reasons: list[str]
    warning: str | None = None


@dataclass
class Suggestion:
    primary_id: int
    candidates: list[Candidate]
    us_person: bool


def profiles(session: Session, ids: Identities) -> dict[int, Profile]:
    out = {root: Profile(root) for root in ids.groups}
    for pid, person in ids.people.items():
        prof = out[ids.root_of[pid]]
        prof.names.add(person.display_name)
        # Only a name that could be a nickname. Never "José N": two of those share no alias.
        if not _masked(person.display_name) and name_key(person.display_name) is None:
            prof.name_forms |= alias_forms(person.display_name)
    for a in session.scalars(select(PersonAttribute)):
        prof = out[ids.root_of[a.person_id]]
        prof.reported.add(a.reported_on)
        if a.document_id is not None:
            prof.docs.add(a.document_id)
        if a.attribute == "alias" and not _masked(a.value):
            prof.aliases |= alias_forms(a.value)
    for pid, actor in session.execute(
        select(PersonOrganization.person_id, PersonOrganization.actor_id)
    ):
        out[ids.root_of[pid]].orgs.add(actor)
    by_doc: dict[int, set[tuple[str, dt.date]]] = defaultdict(set)
    for doc, place, day in session.execute(
        select(event_documents.c.document_id, Event.admin2_name, Event.event_date)
        .join(Event, Event.id == event_documents.c.event_id)
        .where(event_documents.c.document_id.in_({d for p in out.values() for d in p.docs}))
    ):
        if place and day:
            by_doc[doc].add((normalize_alias(place), day))
    for prof in out.values():
        for doc in prof.docs:
            prof.places |= by_doc[doc]
    return out


def _masked(name: str) -> bool:
    return bool(PLACEHOLDERS & set(normalize_alias(name).split()))


def names_agree(a: str, b: str) -> bool:
    """Same name, a masked form of it, or a shorter form of it."""
    x, y = name_words(a), name_words(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long = (a, b) if len(x) <= len(y) else (b, a)
    s, t = name_words(short), name_words(long)
    if _masked(short):
        return t[: len(s)] == s
    return len(s) >= 2 and not _masked(long) and set(s) <= set(t)


def _is_nickname(a: Profile, b: Profile) -> bool:
    """One record's "name" is a nickname the other reports."""
    return any(
        alias_forms(name) & other.aliases and (len(name_words(name)) <= 2)
        for one, other in ((a, b), (b, a))
        for name in one.names
        if not _masked(name)
    )


def _typo(a: str, b: str) -> bool:
    x, y = name_words(a), name_words(b)
    return (
        bool(x and y)
        and SequenceMatcher(None, x[0], y[0]).ratio() >= TYPO_RATIO
        and (_masked(a) or _masked(b))
    )


def _part_of(short: str, long: str) -> bool:
    """A single name word inside a fuller name: "Isidro" in "Fausto Isidro Meza Flores"."""
    s, t = name_words(short), name_words(long)
    return len(s) == 1 and not _masked(short) and s[0] in t


def compare(a: Profile, b: Profile) -> Match | None:
    keys = {k for n in a.names if (k := name_key(n))}
    if keys & {k for n in b.names if (k := name_key(n))}:
        return Match("likely", ("same full name",))
    shared_alias = bool(
        a.aliases & b.aliases or a.aliases & b.name_forms or a.name_forms & b.aliases
    )
    agree = [(x, y) for x in a.names for y in b.names if names_agree(x, y)]
    nickname = _is_nickname(a, b)
    similar = bool(agree or nickname)
    partial = shared_alias and any(
        _typo(x, y) or _part_of(x, y) or _part_of(y, x) for x in a.names for y in b.names
    )
    if not similar and not partial:
        return None
    org = bool(a.orgs & b.orgs)
    incident = any(
        p == q and abs((d - e).days) <= NEAR_DAYS for p, d in a.places for q, e in b.places
    )
    reasons = ["name is the other's nickname" if nickname and not agree else "names agree"]
    if not similar:
        reasons = ["part of the name, or a similar spelling"]
    if shared_alias:
        reasons.append("same alias")
    if org:
        reasons.append("same organization")
    if incident:
        reasons.append(f"same place within {NEAR_DAYS} days")
    if shared_alias:
        close = any(abs((d - e).days) <= CONTEXT_DAYS for d in a.reported for e in b.reported)
        likely = similar and (org or incident or close)
        return Match("likely" if likely else "possible", tuple(reasons))
    # No alias: a lone given name ("José N") may only match another masked name.
    specific = any(
        min(len(name_words(x)), len(name_words(y))) >= 2 or (_masked(x) and _masked(y))
        for x, y in agree
    )
    if specific and (org or incident):
        return Match("possible", tuple(reasons))
    return None


def suggest(session: Session, ids: Identities) -> list[Suggestion]:
    if not ids.people:
        return []
    facts = profiles(session, ids)
    links: dict[int, dict[int, Match]] = defaultdict(dict)
    for a, b in combinations(sorted(facts), 2):
        if not ids.marked_distinct(a, b) and (match := compare(facts[a], facts[b])):
            links[a][b] = links[b][a] = match
    out: list[Suggestion] = []
    placed: set[int] = set()
    for primary in sorted(links, key=lambda r: facts[r].rank(), reverse=True):
        if primary in placed:
            continue
        if found := _gather(ids, facts, links, primary, placed):
            placed |= {primary, *found}
            out.append(_suggestion(ids, facts, primary, found))
    return sorted(out, key=lambda s: -len(s.candidates))


def _gather(
    ids: Identities,
    facts: dict[int, Profile],
    links: dict[int, dict[int, Match]],
    primary: int,
    placed: set[int],
) -> dict[int, Match]:
    """Records to review with ``primary``. Likely links may chain (a nickname record to a full
    name); a possible link never extends the group any further."""
    group = {primary}
    found: dict[int, Match] = {}
    for strength in ("likely", "possible"):
        frontier = [primary, *found]
        while frontier:
            node = frontier.pop(0)
            for other, match in sorted(links[node].items()):
                if other in placed or other in group or match.strength != strength:
                    continue
                if any(ids.marked_distinct(other, g) for g in group):
                    continue
                if node != primary and not _fits(facts[primary], facts[other]):
                    continue
                group.add(other)
                found[other] = match
                if strength == "likely":
                    frontier.append(other)
    return found


def _fits(primary: Profile, other: Profile) -> bool:
    """Stops a chain A~B~C from grouping two different full names."""
    if any(names_agree(x, y) for x in primary.names for y in other.names):
        return True
    if (primary.aliases | primary.name_forms) & (other.aliases | other.name_forms):
        firsts = [
            (name_words(x)[:1], name_words(y)[:1]) for x in primary.names for y in other.names
        ]
        return (
            _is_nickname(primary, other)
            or any(_part_of(x, y) for x in other.names for y in primary.names)
            or any(x == y for x, y in firsts)
        )
    return False


def _suggestion(
    ids: Identities, facts: dict[int, Profile], primary: int, found: dict[int, Match]
) -> Suggestion:
    rows = [Candidate(primary, True, ["fullest reported name"])]
    chosen_docs = set(facts[primary].docs)
    for pid, match in sorted(found.items(), key=lambda kv: (kv[1].strength != "likely", kv[0])):
        together = bool(chosen_docs & facts[pid].docs)
        selected = match.strength == "likely" and not together
        if selected:
            chosen_docs |= facts[pid].docs
        warning = "named separately in the same article" if together else None
        rows.append(Candidate(pid, selected, list(match.reasons), warning))
    return Suggestion(primary, rows, any(ids.us_person(r.person_id) for r in rows))
