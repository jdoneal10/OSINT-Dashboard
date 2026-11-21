"""Person records (hard rule 3; ADR 0008, ADR 0013).

Every claim comes back with its citation: source, date, Admiralty grade and the document it
came from, labeled "as reported". U.S. persons are excluded from lists, search and detail
unless ``include_us_persons`` is set (the owner's EO 12333 boundary). The owner can mark a
record disputed or delete it; deletion removes all of its claims and links.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Actor,
    Event,
    Person,
    PersonAttribute,
    PersonEvent,
    PersonOrganization,
    Source,
)
from app.db.session import get_session
from app.reference.normalize import normalize_alias

router = APIRouter(prefix="/persons", tags=["persons"])
DB = Annotated[Session, Depends(get_session)]
MAX_PAGE = 200
REPORTED = "as reported"


class Citation(BaseModel):
    source: str
    source_url: str | None
    document_id: int | None
    designation_id: int | None
    reported_on: dt.date
    grade: str = Field(description="Admiralty reliability + credibility, e.g. B3")
    evidence: str | None
    basis: str = REPORTED


class Claim(BaseModel):
    kind: str
    value: str
    actor_id: int | None = None
    event_id: int | None = None
    event_date: dt.date | None = None
    citation: Citation


class PersonSummary(BaseModel):
    id: int
    display_name: str
    roles: list[str]
    organizations: list[str]
    n_sources: int
    last_reported_on: dt.date | None
    us_person: bool
    disputed: bool


class PersonPage(BaseModel):
    items: list[PersonSummary]
    total: int


class PersonDetail(PersonSummary):
    dispute_note: str | None
    claims: list[Claim]


class DisputeIn(BaseModel):
    disputed: bool
    note: str | None = Field(default=None, max_length=2000)


def _visible(include_us_persons: bool, include_disputed: bool) -> list[Any]:
    clauses: list[Any] = []
    if not include_us_persons:
        clauses.append(Person.us_person.is_(False))
    if not include_disputed:
        clauses.append(Person.disputed.is_(False))
    return clauses


def _summaries(session: Session, people: list[Person]) -> list[PersonSummary]:
    ids = [p.id for p in people]
    roles: dict[int, list[str]] = defaultdict(list)
    sources: dict[int, set[tuple[int | None, int | None]]] = defaultdict(set)
    last: dict[int, dt.date] = {}
    for a in session.scalars(select(PersonAttribute).where(PersonAttribute.person_id.in_(ids))):
        if a.attribute == "role" and a.value not in roles[a.person_id]:
            roles[a.person_id].append(a.value)
        sources[a.person_id].add((a.document_id, a.designation_id))
        last[a.person_id] = max(last.get(a.person_id, a.reported_on), a.reported_on)
    orgs: dict[int, list[str]] = defaultdict(list)
    for pid, name in session.execute(
        select(PersonOrganization.person_id, Actor.canonical_name)
        .join(Actor, Actor.id == PersonOrganization.actor_id)
        .where(PersonOrganization.person_id.in_(ids))
        .distinct()
    ):
        orgs[pid].append(name)
    return [
        PersonSummary(
            id=p.id,
            display_name=p.display_name,
            roles=roles[p.id],
            organizations=sorted(orgs[p.id]),
            n_sources=len(sources[p.id]),
            last_reported_on=last.get(p.id),
            us_person=p.us_person,
            disputed=p.disputed,
        )
        for p in people
    ]


@router.get("", response_model=PersonPage)
def list_persons(
    session: DB,
    q: Annotated[str | None, Query(description="name or alias")] = None,
    actor: Annotated[int | None, Query(description="linked organization id")] = None,
    include_us_persons: Annotated[
        bool, Query(description="include reported U.S. persons (hidden by default)")
    ] = False,
    include_disputed: bool = True,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PersonPage:
    stmt = select(Person).where(*_visible(include_us_persons, include_disputed))
    if q:
        needle = normalize_alias(q)
        alias_hits = {
            pid
            for pid, value in session.execute(
                select(PersonAttribute.person_id, PersonAttribute.value).where(
                    PersonAttribute.attribute == "alias"
                )
            )
            if needle in normalize_alias(value)
        }
        stmt = stmt.where(
            or_(
                Person.name_key.contains(needle),
                Person.display_name.ilike(f"%{q}%"),
                Person.id.in_(alias_hits),
            )
        )
    if actor is not None:
        stmt = stmt.where(
            Person.id.in_(
                select(PersonOrganization.person_id).where(PersonOrganization.actor_id == actor)
            )
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    people = list(
        session.scalars(stmt.order_by(Person.display_name, Person.id).limit(limit).offset(offset))
    )
    return PersonPage(items=_summaries(session, people), total=total)


def _get(session: Session, person_id: int, include_us_persons: bool) -> Person:
    person = session.get(Person, person_id)
    if person is None or (person.us_person and not include_us_persons):
        raise HTTPException(404, "person not found")
    return person


@router.get("/{person_id}", response_model=PersonDetail)
def get_person(person_id: int, session: DB, include_us_persons: bool = False) -> PersonDetail:
    person = _get(session, person_id, include_us_persons)
    names = dict(session.execute(select(Source.id, Source.name)).all())

    def cite(row: PersonAttribute | PersonOrganization | PersonEvent) -> Citation:
        return Citation(
            source=names.get(row.source_id, "unknown source"),
            source_url=row.source_url,
            document_id=row.document_id,
            designation_id=row.designation_id,
            reported_on=row.reported_on,
            grade=f"{row.reliability}{row.credibility}",
            evidence=row.evidence,
        )

    claims = [
        Claim(kind=a.attribute, value=a.value, citation=cite(a))
        for a in session.scalars(
            select(PersonAttribute).where(PersonAttribute.person_id == person.id)
        )
    ]
    for o, org in session.execute(
        select(PersonOrganization, Actor.canonical_name)
        .join(Actor, Actor.id == PersonOrganization.actor_id)
        .where(PersonOrganization.person_id == person.id)
    ):
        claims.append(
            Claim(
                kind="organization", value=f"{o.role}: {org}", actor_id=o.actor_id, citation=cite(o)
            )
        )
    for e, when in session.execute(
        select(PersonEvent, Event.event_date)
        .join(Event, Event.id == PersonEvent.event_id)
        .where(PersonEvent.person_id == person.id)
    ):
        claims.append(
            Claim(
                kind="event", value=e.role, event_id=e.event_id, event_date=when, citation=cite(e)
            )
        )
    claims.sort(key=lambda c: (c.citation.reported_on, c.kind), reverse=True)
    (summary,) = _summaries(session, [person])
    return PersonDetail(**summary.model_dump(), dispute_note=person.dispute_note, claims=claims)


@router.put("/{person_id}/dispute", response_model=PersonSummary)
def set_dispute(person_id: int, body: DisputeIn, session: DB) -> PersonSummary:
    """Owner control: mark a record disputed (or clear it), with an optional note."""
    person = _get(session, person_id, include_us_persons=True)
    person.disputed = body.disputed
    person.dispute_note = body.note if body.disputed else None
    session.commit()
    (summary,) = _summaries(session, [person])
    return summary


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int, session: DB) -> Response:
    """Owner control: delete a record and every claim and link it has (cascade)."""
    person = _get(session, person_id, include_us_persons=True)
    session.delete(person)
    session.commit()
    return Response(status_code=204)
