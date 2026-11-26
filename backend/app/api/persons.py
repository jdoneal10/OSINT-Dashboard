"""Person records (hard rule 3; ADR 0008, ADR 0013).

Every claim comes back with its citation: source, date, Admiralty grade and the document it
came from, labeled "as reported". U.S. persons are excluded from lists, search and detail
unless ``include_us_persons`` is set (the owner's EO 12333 boundary). The owner can mark a
record disputed or delete it; deletion removes all of its claims and links.

Records the owner merged read as one identity (ADR 0013 amendment 1): any record id resolves
to it, it is hidden if any linked record is a U.S. person, every claim says which name that
source used, and each merge can be undone.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.analytics import person_matches
from app.db.models import (
    Actor,
    Event,
    Person,
    PersonAttribute,
    PersonDistinction,
    PersonEvent,
    PersonMerge,
    PersonOrganization,
    Source,
)
from app.db.session import get_session
from app.enrich import identity
from app.enrich.identity import Identities, MergeError
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
    record_id: int = Field(description="the record this claim was extracted to")
    reported_name: str = Field(description="that record's name, as its source published it")
    actor_id: int | None = None
    event_id: int | None = None
    event_date: dt.date | None = None
    citation: Citation


class PersonSummary(BaseModel):
    id: int
    display_name: str
    roles: list[str]
    organizations: list[str]
    n_sources: int = Field(description="distinct outlets; outlets may reprint one another")
    n_documents: int
    n_records: int
    last_reported_on: dt.date | None
    us_person: bool
    disputed: bool


class PersonPage(BaseModel):
    items: list[PersonSummary]
    total: int


class Record(BaseModel):
    id: int
    display_name: str
    sources: list[str]
    us_person: bool
    merge_id: int | None = Field(description="undo this to separate the record")
    into_id: int | None


class Distinction(BaseModel):
    id: int
    person_id: int
    display_name: str


class PersonDetail(PersonSummary):
    dispute_note: str | None
    claims: list[Claim]
    records: list[Record]
    distinct_from: list[Distinction]


class Candidate(BaseModel):
    person: PersonSummary
    sources: list[str]
    aliases: list[str]
    evidence: str | None
    selected: bool
    reasons: list[str]
    warning: str | None


class Suggestion(BaseModel):
    primary_id: int
    us_person: bool
    candidates: list[Candidate]


class SuggestionList(BaseModel):
    items: list[Suggestion]
    hidden_us_persons: int


class MergeIn(BaseModel):
    person_ids: list[int] = Field(min_length=2, max_length=200)
    primary_id: int
    note: str | None = Field(default=None, max_length=2000)


class DistinctIn(BaseModel):
    person_id: int
    other_ids: list[int] = Field(min_length=1, max_length=200)


class DisputeIn(BaseModel):
    disputed: bool
    note: str | None = Field(default=None, max_length=2000)


def _hidden(ids: Identities, pid: int, include_us: bool, include_disputed: bool = True) -> bool:
    return (not include_us and ids.us_person(pid)) or (not include_disputed and ids.disputed(pid))


def _summaries(session: Session, ids: Identities, roots: list[int]) -> list[PersonSummary]:
    root_of = {m: r for r in roots for m in ids.groups[r]}
    records = list(root_of)
    roles: dict[int, list[str]] = defaultdict(list)
    docs: dict[int, set[tuple[int | None, int | None]]] = defaultdict(set)
    outlets: dict[int, set[int]] = defaultdict(set)
    last: dict[int, dt.date] = {}
    for a in session.scalars(
        select(PersonAttribute)
        .where(PersonAttribute.person_id.in_(records))
        .order_by(PersonAttribute.id)
    ):
        root = root_of[a.person_id]
        if a.attribute == "role" and a.value not in roles[root]:
            roles[root].append(a.value)
        docs[root].add((a.document_id, a.designation_id))
        outlets[root].add(a.source_id)
        last[root] = max(last.get(root, a.reported_on), a.reported_on)
    orgs: dict[int, set[str]] = defaultdict(set)
    for pid, name in session.execute(
        select(PersonOrganization.person_id, Actor.canonical_name)
        .join(Actor, Actor.id == PersonOrganization.actor_id)
        .where(PersonOrganization.person_id.in_(records))
        .distinct()
    ):
        orgs[root_of[pid]].add(name)
    return [
        PersonSummary(
            id=r,
            display_name=ids.people[r].display_name,
            roles=roles[r],
            organizations=sorted(orgs[r]),
            n_sources=len(outlets[r]),
            n_documents=len(docs[r]),
            n_records=len(ids.groups[r]),
            last_reported_on=last.get(r),
            us_person=ids.us_person(r),
            disputed=ids.disputed(r),
        )
        for r in roots
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
    ids = identity.load(session)
    roots = {r for r in ids.groups if not _hidden(ids, r, include_us_persons, include_disputed)}
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
        found = session.scalars(
            select(Person.id).where(
                or_(
                    Person.name_key.contains(needle),
                    Person.display_name.ilike(f"%{q}%"),
                    Person.id.in_(alias_hits),
                )
            )
        )
        hits = set(found) | {
            p.id for p in ids.people.values() if needle in normalize_alias(p.display_name)
        }
        roots &= {ids.root_of[i] for i in hits}
    if actor is not None:
        linked = session.scalars(
            select(PersonOrganization.person_id).where(PersonOrganization.actor_id == actor)
        )
        roots &= {ids.root_of[i] for i in linked}
    ordered = sorted(roots, key=lambda r: (normalize_alias(ids.people[r].display_name), r))
    page = _summaries(session, ids, ordered[offset : offset + limit])
    return PersonPage(items=page, total=len(ordered))


@router.get("/merge-suggestions", response_model=SuggestionList)
def merge_suggestions(session: DB, include_us_persons: bool = False) -> SuggestionList:
    """Possible duplicates for review. Nothing here merges records."""
    ids = identity.load(session)
    found = person_matches.suggest(session, ids)
    shown = [s for s in found if include_us_persons or not s.us_person]
    roots = [c.person_id for s in shown for c in s.candidates]
    summary = {p.id: p for p in _summaries(session, ids, roots)}
    facts = _facts(session, [m for r in roots for m in ids.groups[r]])
    items = []
    for s in shown:
        rows = []
        for c in s.candidates:
            members = ids.groups[c.person_id]
            rows.append(
                Candidate(
                    person=summary[c.person_id],
                    sources=sorted({n for m in members for n in facts[m][0]}),
                    aliases=sorted({a for m in members for a in facts[m][1]}),
                    evidence=next((facts[m][2] for m in members if facts[m][2]), None),
                    selected=c.selected,
                    reasons=c.reasons,
                    warning=c.warning,
                )
            )
        items.append(Suggestion(primary_id=s.primary_id, us_person=s.us_person, candidates=rows))
    return SuggestionList(items=items, hidden_us_persons=len(found) - len(shown))


def _facts(
    session: Session, records: list[int]
) -> dict[int, tuple[set[str], set[str], str | None]]:
    """(outlets, aliases, a quote) per record."""
    outlets: dict[int, set[str]] = defaultdict(set)
    aliases: dict[int, set[str]] = defaultdict(set)
    quotes: dict[int, str] = {}
    for a, source in session.execute(
        select(PersonAttribute, Source.name)
        .join(Source, Source.id == PersonAttribute.source_id)
        .where(PersonAttribute.person_id.in_(records))
        .order_by(PersonAttribute.id)
    ):
        outlets[a.person_id].add(source)
        if a.attribute == "alias":
            aliases[a.person_id].add(a.value)
        if a.evidence:
            quotes.setdefault(a.person_id, a.evidence)
    return {r: (outlets[r], aliases[r], quotes.get(r)) for r in records}


@router.post("/merges", response_model=PersonSummary)
def merge_persons(body: MergeIn, session: DB) -> PersonSummary:
    """Owner decision: these records are one person. Claims and labels do not move."""
    try:
        identity.merge(session, body.person_ids, body.primary_id, body.note)
    except MergeError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    (summary,) = _summaries(session, identity.load(session), [body.primary_id])
    return summary


@router.post("/merges/{merge_id}/undo", status_code=204)
def undo_merge(merge_id: int, session: DB) -> Response:
    if identity.undo(session, merge_id) is None:
        raise HTTPException(404, "active merge not found")
    session.commit()
    return Response(status_code=204)


@router.post("/distinctions", status_code=204)
def mark_not_same(body: DistinctIn, session: DB) -> Response:
    """Owner decision: not the same person. Never suggested or merged again."""
    try:
        identity.mark_distinct(session, body.person_id, body.other_ids)
    except MergeError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return Response(status_code=204)


@router.delete("/distinctions/{distinction_id}", status_code=204)
def clear_not_same(distinction_id: int, session: DB) -> Response:
    row = session.get(PersonDistinction, distinction_id)
    if row is None:
        raise HTTPException(404, "decision not found")
    session.delete(row)
    session.commit()
    return Response(status_code=204)


def _get(session: Session, person_id: int, include_us_persons: bool) -> tuple[Identities, int]:
    ids = identity.load(session)
    if person_id not in ids.people or _hidden(ids, person_id, include_us_persons):
        raise HTTPException(404, "person not found")
    return ids, ids.root_of[person_id]


@router.get("/{person_id}", response_model=PersonDetail)
def get_person(person_id: int, session: DB, include_us_persons: bool = False) -> PersonDetail:
    ids, root = _get(session, person_id, include_us_persons)
    members = ids.groups[root]
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

    def record(row: PersonAttribute | PersonOrganization | PersonEvent) -> dict[str, Any]:
        return {
            "record_id": row.person_id,
            "reported_name": ids.people[row.person_id].display_name,
            "citation": cite(row),
        }

    claims = [
        Claim(kind=a.attribute, value=a.value, **record(a))
        for a in session.scalars(
            select(PersonAttribute).where(PersonAttribute.person_id.in_(members))
        )
    ]
    for o, org in session.execute(
        select(PersonOrganization, Actor.canonical_name)
        .join(Actor, Actor.id == PersonOrganization.actor_id)
        .where(PersonOrganization.person_id.in_(members))
    ):
        claims.append(
            Claim(kind="organization", value=f"{o.role}: {org}", actor_id=o.actor_id, **record(o))
        )
    for e, when in session.execute(
        select(PersonEvent, Event.event_date)
        .join(Event, Event.id == PersonEvent.event_id)
        .where(PersonEvent.person_id.in_(members))
    ):
        claims.append(
            Claim(kind="event", value=e.role, event_id=e.event_id, event_date=when, **record(e))
        )
    claims.sort(key=lambda c: (c.citation.reported_on, c.kind), reverse=True)
    links = {
        m.member_id: m
        for m in session.scalars(
            select(PersonMerge).where(
                PersonMerge.member_id.in_(members), PersonMerge.undone_at.is_(None)
            )
        )
    }
    facts = _facts(session, members)
    records = [
        Record(
            id=m,
            display_name=ids.people[m].display_name,
            sources=sorted(facts[m][0]),
            us_person=ids.people[m].us_person,
            merge_id=links[m].id if m in links else None,
            into_id=links[m].into_id if m in links else None,
        )
        for m in sorted(members, key=lambda m: (m != root, m))
    ]
    others = []
    for d in session.scalars(
        select(PersonDistinction).where(
            or_(PersonDistinction.a_id.in_(members), PersonDistinction.b_id.in_(members))
        )
    ):
        other = d.b_id if d.a_id in members else d.a_id
        if not _hidden(ids, other, include_us_persons):
            others.append(
                Distinction(id=d.id, person_id=other, display_name=ids.people[other].display_name)
            )
    note = next(
        (p.dispute_note for p in [ids.people[root], *ids.members(root)] if p.dispute_note), None
    )
    (summary,) = _summaries(session, ids, [root])
    return PersonDetail(
        **summary.model_dump(),
        dispute_note=note,
        claims=claims,
        records=records,
        distinct_from=others,
    )


@router.put("/{person_id}/dispute", response_model=PersonSummary)
def set_dispute(person_id: int, body: DisputeIn, session: DB) -> PersonSummary:
    """Owner control: mark a record disputed (or clear it), with an optional note."""
    ids, root = _get(session, person_id, include_us_persons=True)
    for person in ids.members(root):
        person.disputed = body.disputed
        person.dispute_note = body.note if body.disputed else None
    session.commit()
    (summary,) = _summaries(session, identity.load(session), [root])
    return summary


@router.delete("/{person_id}", status_code=204)
def delete_person(person_id: int, session: DB) -> Response:
    """Owner control: delete an identity: every linked record, claim and link (cascade)."""
    ids, root = _get(session, person_id, include_us_persons=True)
    session.execute(delete(Person).where(Person.id.in_(ids.groups[root])))
    session.commit()
    return Response(status_code=204)
