"""Actor directory (organizations only; CLAUDE.md hard rule 3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import ACTOR_TYPES, Actor, ActorAlias, actor_events, designation_actors
from app.db.session import get_session
from app.reference.normalize import normalize_alias

router = APIRouter(prefix="/actors", tags=["actors"])


class ActorOut(BaseModel):
    id: int
    slug: str
    name: str
    actor_type: str
    parent_id: int | None
    aliases: list[str]
    event_count: int
    designation_count: int


@router.get("", response_model=list[ActorOut])
def list_actors(
    session: Annotated[Session, Depends(get_session)],
    q: Annotated[str | None, Query(description="name or alias, accent-insensitive")] = None,
    actor_type: Annotated[list[str] | None, Query(alias="type")] = None,
    with_events: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ActorOut]:
    events = (
        select(func.count(func.distinct(actor_events.c.event_id)))
        .where(actor_events.c.actor_id == Actor.id)
        .correlate(Actor)
        .scalar_subquery()
    )
    designations = (
        select(func.count())
        .where(designation_actors.c.actor_id == Actor.id)
        .correlate(Actor)
        .scalar_subquery()
    )
    stmt = select(Actor, events.label("n_events"), designations)
    if q:
        key = f"%{normalize_alias(q)}%"
        stmt = stmt.where(
            or_(
                Actor.id.in_(
                    select(ActorAlias.actor_id).where(ActorAlias.alias_normalized.like(key))
                ),
                func.lower(Actor.canonical_name).like(f"%{q.lower()}%"),
            )
        )
    if actor_type:
        stmt = stmt.where(Actor.actor_type.in_([t for t in actor_type if t in ACTOR_TYPES]))
    if with_events:
        stmt = stmt.where(events > 0)
    rows = session.execute(stmt.order_by(events.desc(), Actor.canonical_name).limit(limit)).all()
    ids = [a.id for a, _, _ in rows]
    aliases: dict[int, list[str]] = {}
    for actor_id, alias in session.execute(
        select(ActorAlias.actor_id, ActorAlias.alias)
        .where(ActorAlias.actor_id.in_(ids))
        .order_by(ActorAlias.alias)
    ):
        aliases.setdefault(actor_id, []).append(alias)
    return [
        ActorOut(
            id=a.id,
            slug=a.slug,
            name=a.canonical_name,
            actor_type=a.actor_type,
            parent_id=a.parent_id,
            aliases=aliases.get(a.id, []),
            event_count=n,
            designation_count=d,
        )
        for a, n, d in rows
    ]
