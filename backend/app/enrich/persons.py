"""Person records from extraction (hard rule 3; ADR 0008, ADR 0013).

Every stored claim (role, alias, nationality, status, title, organization link, event link)
is one row citing the document it came from, with the date and Admiralty grade. Safeguards
applied here, after the prompt's own rules:

- people the text reports as minors are dropped;
- names, aliases and titles that look like contact or ID details are dropped;
- a reported U.S. nexus sets ``us_person`` (hidden by default in views and search);
- names and aliases the cited text does not contain are not stored, and family details and
  third-party names are kept out of titles and quotes (``app.enrich.person_guard``);
- matching is conservative: only an exact normalized full name of three or more name words
  (particles such as "de la" do not count), not a nickname and without a placeholder such as
  "N", joins an existing person; anything thinner starts a new record for the owner to
  review (``app.enrich.identity``);
- re-extraction reuses the document's own records, so disputes, merges and labels stay;
- re-extracting a document replaces its claims, and a person left with no citation is
  deleted, so no uncited person exists.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Protocol

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    Person,
    PersonAttribute,
    PersonEvent,
    PersonOrganization,
    Source,
)
from app.enrich import identity, person_guard
from app.enrich.admiralty import credibility
from app.ingest.publication import published_day
from app.reference.normalize import normalize_alias

PARTICLES = frozenset({"de", "del", "la", "las", "los", "el", "y"})
NICKNAME_START = frozenset({"el", "la", "los", "las"})
MIN_NAME_WORDS = 3  # given name plus surnames; two words can be two given names or a nickname
# Phone numbers, emails, URLs, long digit runs (IDs, accounts): never stored as person data.
_CONTACT_LIKE = re.compile(
    r"@|https?://|www\.|\d[\d\s().-]{6,}\d|\b(curp|rfc|ine|pasaporte|passport)\b", re.I
)


log = logging.getLogger(__name__)


class PersonLike(Protocol):
    """Read-only view of an extracted person (``extract.ExtractedPerson``)."""

    @property
    def name(self) -> str: ...
    @property
    def aliases(self) -> Sequence[str]: ...
    @property
    def role(self) -> str: ...
    @property
    def organization(self) -> str | None: ...
    @property
    def nationality(self) -> str | None: ...
    @property
    def us_nexus(self) -> bool: ...
    @property
    def reported_minor(self) -> bool: ...
    @property
    def statuses(self) -> Sequence[str]: ...
    @property
    def title(self) -> str | None: ...
    @property
    def evidence(self) -> str: ...


@dataclass(frozen=True)
class Citation:
    source_id: int
    document_id: int
    source_url: str | None
    reported_on: dt.date
    reliability: str
    credibility: int
    evidence: str | None
    llm_model: str | None
    prompt_version: str | None

    def row(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "source_url": self.source_url,
            "reported_on": self.reported_on,
            "reliability": self.reliability,
            "credibility": self.credibility,
            "evidence": self.evidence,
            "llm_model": self.llm_model,
            "prompt_version": self.prompt_version,
        }


def name_words(name: str) -> list[str]:
    """The words of a name that identify someone: no particles, no "N" placeholder."""
    skip = PARTICLES | person_guard.PLACEHOLDERS
    return [t for t in normalize_alias(name).split() if t not in skip]


def name_key(name: str) -> str | None:
    """Normalized full name for matching, or None when too thin to match safely."""
    tokens = normalize_alias(name).split()
    if not tokens or tokens[0] in NICKNAME_START:
        return None
    if (person_guard.PLACEHOLDERS | {"alias"}) & set(tokens):
        return None
    if len(name_words(name)) < MIN_NAME_WORDS:
        return None
    return " ".join(tokens)


def alias_forms(value: str) -> set[str]:
    """Comparable forms of a nickname: "#ElTopo", "El Topo" and "Topo" share "topo"."""
    spaced = re.sub(r"(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÑ])", " ", value)
    words = normalize_alias(spaced).split()
    forms = {"".join(words)}
    if len(words) > 1 and words[0] in NICKNAME_START:
        forms.add("".join(words[1:]))
    return forms - {""}


@dataclass(frozen=True)
class Prior:
    """A record this document cited before re-extraction."""

    person_id: int
    name: str
    aliases: frozenset[str]


def prior_records(session: Session, document_id: int) -> list[Prior]:
    """The document's records, read before its claims are cleared."""
    aliases: dict[int, set[str]] = {}
    for a in session.scalars(
        select(PersonAttribute).where(PersonAttribute.document_id == document_id)
    ):
        forms = aliases.setdefault(a.person_id, set())
        if a.attribute == "alias":
            forms |= alias_forms(a.value)
    people = session.scalars(select(Person).where(Person.id.in_(aliases)).order_by(Person.id))
    return [Prior(p.id, p.display_name, frozenset(aliases[p.id])) for p in people]


def clean_value(value: str | None, limit: int = 256) -> str | None:
    """Trimmed value, or None when empty or contact/ID-like (hard rule 3)."""
    if value is None:
        return None
    text = " ".join(value.split())[:limit]
    if not text or _CONTACT_LIKE.search(text):
        return None
    return text


def citation_for(doc: Document, source: Source, evidence: str | None, *, model: str,
                 prompt_version: str) -> Citation:  # fmt: skip
    rel = source.reliability or "F"
    return Citation(
        source_id=source.id,
        document_id=doc.id,
        source_url=doc.source_url,
        reported_on=published_day(doc, source.slug),
        reliability=rel,
        credibility=credibility(1, rel, conflicted=False),
        evidence=clean_value(evidence, 300),
        llm_model=model,
        prompt_version=prompt_version,
    )


def clear_document(session: Session, document_id: int) -> None:
    """Remove a document's person claims (before re-extraction)."""
    for model in (PersonAttribute, PersonOrganization, PersonEvent):
        session.execute(delete(model).where(model.document_id == document_id))


def delete_uncited(session: Session) -> int:
    """Delete persons with no remaining citation; returns how many."""
    cited = [
        exists().where(m.person_id == Person.id)
        for m in (PersonAttribute, PersonOrganization, PersonEvent)
    ]
    uncited = ~or_(*cited)
    identity.relink_before_delete(session, set(session.scalars(select(Person.id).where(uncited))))
    result = session.execute(delete(Person).where(uncited))
    return int(getattr(result, "rowcount", 0) or 0)


def _previous(name: str, aliases: Sequence[str], prior: Sequence[Prior]) -> Prior | None:
    """The record this document gave the same person last time, if there is exactly that."""
    wanted = normalize_alias(name)
    for p in prior:  # in extraction order, so two "Juan N" keep their own records
        if normalize_alias(p.name) == wanted:
            return p
    forms = set().union(*(alias_forms(a) for a in aliases))
    first = wanted.split()[:1]
    hits = [
        p
        for p in prior
        if forms & p.aliases
        and (normalize_alias(p.name).split()[:1] == first or alias_forms(p.name) & forms)
    ]
    return hits[0] if len(hits) == 1 else None


def _has_claims(session: Session, person_id: int) -> bool:
    return any(
        session.scalar(select(m.id).where(m.person_id == person_id).limit(1)) is not None
        for m in (PersonAttribute, PersonOrganization, PersonEvent)
    )


def _by_key(session: Session, key: str) -> Person | None:
    """The record with this full name, unless the owner said two of that name differ."""
    people = list(session.scalars(select(Person).where(Person.name_key == key).order_by(Person.id)))
    if len(people) > 1:
        ids = identity.load(session)
        if any(ids.marked_distinct(a.id, b.id) for a, b in combinations(people, 2)):
            return None
    return people[0] if people else None


def _person(
    session: Session, name: str, aliases: Sequence[str], us_nexus: bool, prior: list[Prior]
) -> Person:
    key = name_key(name)
    person = None
    if (before := _previous(name, aliases, prior)) is not None:
        prior.remove(before)
        person = session.get_one(Person, before.person_id)
        if not _has_claims(session, person.id):  # only this document named the record
            person.display_name, person.name_key = name, key
    elif key is not None:
        person = _by_key(session, key)
    if person is None:
        person = Person(display_name=name, name_key=key)
        session.add(person)
        session.flush()
    if us_nexus:
        person.us_person = True
    return person


def _add(session: Session, model: type, values: dict[str, object]) -> None:
    session.execute(insert(model).values(**values).on_conflict_do_nothing())


def store_persons(
    session: Session,
    people: Sequence[PersonLike],
    cite: Callable[[str | None], Citation],
    *,
    actor_id: Callable[[str], int | None],
    event_links: Sequence[Sequence[tuple[int, str]]],
    text: str,
    prior: Sequence[Prior] = (),
) -> int:
    """Store one document's persons. ``event_links[i]`` holds (event_id, role) pairs for
    ``people[i]``; ``actor_id`` resolves an organization name; ``text`` is what the model was
    shown; ``prior`` is ``prior_records`` from before the claims were cleared. Returns persons
    stored."""
    stored = 0
    unclaimed = list(prior)
    # People a quote may name: those listed here, never someone dropped as a minor.
    listed = [v for p in people if not p.reported_minor for v in (p.name, *p.aliases)]
    for i, p in enumerate(people):
        if p.reported_minor or clean_value(p.name, 256) is None:
            continue
        aliases = [a for a in p.aliases if clean_value(a) and person_guard.in_text(a, text)]
        name = clean_value(person_guard.supported_name(p.name, text, aliases), 256)
        if name is None:
            log.warning("person not stored: name not in the cited text")  # never log the name
            continue
        person = _person(session, name, aliases, p.us_nexus, unclaimed)
        c = cite(person_guard.safe_quote(p.evidence, listed)).row() | {"person_id": person.id}
        _add(session, PersonAttribute, c | {"attribute": "role", "value": p.role})
        values: list[tuple[str, str | None]] = [("alias", a) for a in aliases]
        values += [("status", s) for s in p.statuses]
        values += [("nationality", p.nationality), ("title", person_guard.clean_title(p.title))]
        for attribute, raw in values:
            if (value := clean_value(raw)) is not None:
                _add(session, PersonAttribute, c | {"attribute": attribute, "value": value})
        if p.organization and (aid := actor_id(p.organization)) is not None:
            _add(session, PersonOrganization, c | {"actor_id": aid, "role": p.role})
        for event_id, role in event_links[i] if i < len(event_links) else ():
            _add(session, PersonEvent, c | {"event_id": event_id, "role": role})
        stored += 1
    return stored
