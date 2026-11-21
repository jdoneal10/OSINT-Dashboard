"""Person records from extraction (hard rule 3; ADR 0008, ADR 0013).

Every stored claim (role, alias, nationality, status, title, organization link, event link)
is one row citing the document it came from, with the date and Admiralty grade. Safeguards
applied here, after the prompt's own rules:

- people the text reports as minors are dropped;
- names, aliases and titles that look like contact or ID details are dropped;
- a reported U.S. nexus sets ``us_person`` (hidden by default in views and search);
- matching is conservative: only an exact normalized full name of two or more words, without
  a placeholder such as "N", joins an existing person; anything thinner starts a new record;
- re-extracting a document replaces its claims, and a person left with no citation is
  deleted, so no uncited person exists.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from app.enrich.admiralty import credibility
from app.reference.normalize import normalize_alias

PLACEHOLDERS = frozenset({"n", "nn", "x", "xx", "alias", "el", "la"})
MIN_NAME_TOKENS = 2
# Phone numbers, emails, URLs, long digit runs (IDs, accounts): never stored as person data.
_CONTACT_LIKE = re.compile(
    r"@|https?://|www\.|\d[\d\s().-]{6,}\d|\b(curp|rfc|ine|pasaporte|passport)\b", re.I
)


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


def name_key(name: str) -> str | None:
    """Normalized full name for matching, or None when too thin to match safely."""
    tokens = normalize_alias(name).split()
    if len(tokens) < MIN_NAME_TOKENS or PLACEHOLDERS & set(tokens):
        return None
    return " ".join(tokens)


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
        reported_on=(doc.published_at or doc.retrieved_at).date(),
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
    result = session.execute(delete(Person).where(~or_(*cited)))
    return int(getattr(result, "rowcount", 0) or 0)


def _person(session: Session, name: str, us_nexus: bool) -> Person:
    key = name_key(name)
    person = None
    if key is not None:
        person = session.scalars(
            select(Person).where(Person.name_key == key).order_by(Person.id).limit(1)
        ).first()
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
) -> int:
    """Store one document's persons. ``event_links[i]`` holds (event_id, role) pairs for
    ``people[i]``; ``actor_id`` resolves an organization name. Returns persons stored."""
    stored = 0
    for i, p in enumerate(people):
        name = clean_value(p.name, 256)
        if p.reported_minor or name is None:
            continue
        person = _person(session, name, p.us_nexus)
        c = cite(p.evidence).row() | {"person_id": person.id}
        _add(session, PersonAttribute, c | {"attribute": "role", "value": p.role})
        values: list[tuple[str, str | None]] = [("alias", a) for a in p.aliases]
        values += [("status", s) for s in p.statuses]
        values += [("nationality", p.nationality), ("title", p.title)]
        for attribute, raw in values:
            if (value := clean_value(raw)) is not None:
                _add(session, PersonAttribute, c | {"attribute": attribute, "value": value})
        if p.organization and (aid := actor_id(p.organization)) is not None:
            _add(session, PersonOrganization, c | {"actor_id": aid, "role": p.role})
        for event_id, role in event_links[i] if i < len(event_links) else ():
            _add(session, PersonEvent, c | {"event_id": event_id, "role": role})
        stored += 1
    return stored
