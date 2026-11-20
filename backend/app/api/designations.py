"""Public legal actions: OFAC SDN listings, FTO and SDGT designations (ADR 0004).

Individual SDN listings are hidden by default (CLAUDE.md hard rule 3): named people appear
only as attributes of a public record, and this API offers no search by personal name.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import cast, func, not_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.db.models import DESIGNATION_TYPES, Actor, Designation, Source, designation_actors
from app.db.session import get_session

router = APIRouter(prefix="/designations", tags=["designations"])
DB = Annotated[Session, Depends(get_session)]


class ActorRef(BaseModel):
    id: int
    name: str


class DesignationOut(BaseModel):
    id: int
    source: str
    source_url: str | None
    retrieved_at: dt.datetime
    designation_type: str
    program: str | None
    action: str
    action_date: dt.date
    title: str
    listed_parties: list[dict[str, Any]]
    actors: list[ActorRef]


class DesignationPage(BaseModel):
    items: list[DesignationOut]
    total: int


def _is_individual() -> Any:
    """Listing whose party is a person (``listed_parties @> [{"type": "individual"}]``)."""
    return cast(Designation.listed_parties, JSONB).contains([{"type": "individual"}])


@router.get("", response_model=DesignationPage)
def list_designations(
    session: DB,
    designation_type: Annotated[
        list[str] | None, Query(alias="type", description=f"{DESIGNATION_TYPES}")
    ] = None,
    program: Annotated[str | None, Query(description="e.g. SDNTK, TCO, FTO")] = None,
    actor: Annotated[list[int] | None, Query(description="linked actor ids")] = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    include_individual_listings: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DesignationPage:
    """Newest first. Program matching is per-token (``SDNTK`` matches ``SDGT;SDNTK``)."""
    stmt = select(Designation, Source.slug).join(Source, Source.id == Designation.source_id)
    if designation_type:
        stmt = stmt.where(Designation.designation_type.in_(designation_type))
    if program:
        tokens = func.string_to_array(Designation.program, ";")
        stmt = stmt.where(func.array_position(tokens, program.upper()).is_not(None))
    if actor:
        stmt = stmt.where(
            Designation.id.in_(
                select(designation_actors.c.designation_id).where(
                    designation_actors.c.actor_id.in_(actor)
                )
            )
        )
    if start:
        stmt = stmt.where(Designation.action_date >= start)
    if end:
        stmt = stmt.where(Designation.action_date <= end)
    if not include_individual_listings:
        stmt = stmt.where(not_(_is_individual()))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(
        stmt.order_by(Designation.action_date.desc(), Designation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    ids = [d.id for d, _ in rows]
    actors: dict[int, list[ActorRef]] = {}
    for did, aid, name in session.execute(
        select(designation_actors.c.designation_id, Actor.id, Actor.canonical_name)
        .join(Actor, Actor.id == designation_actors.c.actor_id)
        .where(designation_actors.c.designation_id.in_(ids))
        .order_by(Actor.canonical_name)
    ):
        actors.setdefault(did, []).append(ActorRef(id=aid, name=name))
    items = [
        DesignationOut(
            id=d.id,
            source=slug,
            source_url=d.source_url,
            retrieved_at=d.retrieved_at,
            designation_type=d.designation_type,
            program=d.program,
            action=d.action,
            action_date=d.action_date,
            title=d.title,
            listed_parties=d.listed_parties,
            actors=actors.get(d.id, []),
        )
        for d, slug in rows
    ]
    return DesignationPage(items=items, total=total)
