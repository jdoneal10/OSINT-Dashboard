"""Event endpoints: ACLED (internal use only, ADR 0003) and news-derived events (ADR 0004).

News-derived events outside the AOI are hidden unless ``include_out_of_aoi=true``.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geometry
from pydantic import BaseModel
from sqlalchemy import Select, cast, func, select, tuple_
from sqlalchemy.orm import Session

from app.db.models import Actor, Event, Source, actor_events, event_documents
from app.db.session import get_session

router = APIRouter(prefix="/events", tags=["events"])

MAX_PAGE = 500
MAX_POINTS = 50_000


class EventFilters(BaseModel):
    start: dt.date | None = None
    end: dt.date | None = None
    event_type: list[str] | None = None
    actor: list[int] | None = None
    admin1: list[str] | None = None
    bbox: tuple[float, float, float, float] | None = None
    source: list[str] | None = None
    include_out_of_aoi: bool = False


def event_filters(
    start: dt.date | None = None,
    end: dt.date | None = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    actor: Annotated[list[int] | None, Query(description="actor ids; factions included")] = None,
    admin1: Annotated[list[str] | None, Query(description="e.g. MX-BCN")] = None,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat")] = None,
    source: Annotated[list[str] | None, Query(description="source slugs, e.g. acled, doj")] = None,
    include_out_of_aoi: Annotated[
        bool, Query(description="include news-derived events outside the AOI")
    ] = False,
) -> EventFilters:
    box = None
    if bbox:
        try:
            parts = [float(p) for p in bbox.split(",")]
        except ValueError:
            parts = []
        if len(parts) != 4:
            raise HTTPException(422, "bbox must be minLon,minLat,maxLon,maxLat")
        box = (parts[0], parts[1], parts[2], parts[3])
    return EventFilters(
        start=start,
        end=end,
        event_type=event_type,
        actor=actor,
        admin1=admin1,
        bbox=box,
        source=source,
        include_out_of_aoi=include_out_of_aoi,
    )


Filters = Annotated[EventFilters, Depends(event_filters)]
DB = Annotated[Session, Depends(get_session)]


def _with_descendants(session: Session, ids: list[int]) -> list[int]:
    children: dict[int, list[int]] = {}
    for actor_id, parent_id in session.execute(select(Actor.id, Actor.parent_id)):
        if parent_id is not None:
            children.setdefault(parent_id, []).append(actor_id)
    out, stack = set(ids), list(ids)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return sorted(out)


def apply_filters[T: Any](stmt: Select[T], f: EventFilters, session: Session) -> Select[T]:
    if not f.include_out_of_aoi:
        stmt = stmt.where(Event.in_aoi.is_(True))
    if f.source:
        stmt = stmt.where(Event.source_id.in_(select(Source.id).where(Source.slug.in_(f.source))))
    if f.start:
        stmt = stmt.where(Event.event_date >= f.start)
    if f.end:
        stmt = stmt.where(Event.event_date <= f.end)
    if f.event_type:
        stmt = stmt.where(Event.event_type.in_(f.event_type))
    if f.admin1:
        stmt = stmt.where(Event.admin1_code.in_(f.admin1))
    if f.actor:
        ids = _with_descendants(session, f.actor)
        stmt = stmt.where(
            Event.id.in_(select(actor_events.c.event_id).where(actor_events.c.actor_id.in_(ids)))
        )
    if f.bbox:
        stmt = stmt.where(
            func.ST_Intersects(cast(Event.geom, Geometry), func.ST_MakeEnvelope(*f.bbox, 4326))
        )
    return stmt


def actors_for(session: Session, event_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    if not event_ids:
        return out
    rows = session.execute(
        select(
            actor_events.c.event_id,
            actor_events.c.role,
            Actor.id,
            Actor.canonical_name,
            Actor.actor_type,
        )
        .join(Actor, Actor.id == actor_events.c.actor_id)
        .where(actor_events.c.event_id.in_(event_ids))
        .order_by(actor_events.c.role, Actor.canonical_name)
    ).all()
    for event_id, role, actor_id, name, actor_type in rows:
        out.setdefault(event_id, []).append(
            {"id": actor_id, "name": name, "type": actor_type, "role": role}
        )
    return out


def documents_for(session: Session, event_ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    if not event_ids:
        return out
    rows = session.execute(
        select(event_documents.c.event_id, event_documents.c.document_id)
        .where(event_documents.c.event_id.in_(event_ids))
        .order_by(event_documents.c.document_id)
    )
    for event_id, document_id in rows:
        out.setdefault(event_id, []).append(document_id)
    return out


class EventOut(BaseModel):
    id: int
    source: str
    source_key: str
    source_url: str | None
    retrieved_at: dt.datetime
    confidence: float | None
    event_date: dt.date
    event_type: str
    sub_event_type: str | None
    fatalities: int | None
    lon: float | None
    lat: float | None
    geo_precision: int | None
    time_precision: int | None
    admin1_code: str | None
    admin1_name: str | None
    admin2_name: str | None
    location_name: str | None
    description: str | None
    credibility: int | None
    cluster_id: int | None
    in_aoi: bool
    actors: list[dict[str, Any]]
    document_ids: list[int]  # documents this event was derived from (empty for ACLED)


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: str | None


def event_select() -> Select[Any]:
    point = cast(Event.geom, Geometry)
    return select(Event, Source.slug, func.ST_X(point), func.ST_Y(point)).join(
        Source, Source.id == Event.source_id
    )


def event_out(
    row: Any, actors: dict[int, list[dict[str, Any]]], docs: dict[int, list[int]]
) -> EventOut:
    ev, slug, lon, lat = row
    return EventOut(
        id=ev.id,
        source=slug,
        source_key=ev.source_key,
        source_url=ev.source_url,
        retrieved_at=ev.retrieved_at,
        confidence=float(ev.confidence) if ev.confidence is not None else None,
        event_date=ev.event_date,
        event_type=ev.event_type,
        sub_event_type=ev.sub_event_type,
        fatalities=ev.fatalities,
        lon=lon,
        lat=lat,
        geo_precision=ev.geo_precision,
        time_precision=ev.time_precision,
        admin1_code=ev.admin1_code,
        admin1_name=ev.admin1_name,
        admin2_name=ev.admin2_name,
        location_name=ev.location_name,
        description=ev.description,
        credibility=ev.credibility,
        cluster_id=ev.cluster_id,
        in_aoi=ev.in_aoi,
        actors=actors.get(ev.id, []),
        document_ids=docs.get(ev.id, []),
    )


@router.get("", response_model=EventPage)
def list_events(
    session: DB,
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
    cursor: Annotated[str | None, Query(description="opaque; from next_cursor")] = None,
) -> EventPage:
    """Newest first, keyset-paginated, with full provenance and linked actors."""
    stmt = apply_filters(event_select(), filters, session)
    if cursor:
        try:
            date_s, id_s = cursor.split("_", 1)
            key = (dt.date.fromisoformat(date_s), int(id_s))
        except ValueError as exc:
            raise HTTPException(422, "invalid cursor") from exc
        stmt = stmt.where(tuple_(Event.event_date, Event.id) < tuple_(*key))
    rows = session.execute(
        stmt.order_by(Event.event_date.desc(), Event.id.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    ids = [r[0].id for r in page]
    actors, docs = actors_for(session, ids), documents_for(session, ids)
    items = [event_out(r, actors, docs) for r in page]
    nxt = f"{page[-1][0].event_date}_{page[-1][0].id}" if len(rows) > limit else None
    return EventPage(items=items, next_cursor=nxt)


class EventTypeCount(BaseModel):
    event_type: str
    events: int


@router.get("/types", response_model=list[EventTypeCount])
def event_types(session: DB) -> list[EventTypeCount]:
    rows = session.execute(
        select(Event.event_type, func.count())
        .group_by(Event.event_type)
        .order_by(func.count().desc())
    ).all()
    return [EventTypeCount(event_type=t, events=n) for t, n in rows]


@router.get("/geojson")
def events_geojson(session: DB, filters: Filters) -> dict[str, Any]:
    """Compact points for the map. Properties: id, d (date), t (type), f (fatalities),
    gp (geo precision), a (actor ids)."""
    point = cast(Event.geom, Geometry)
    actor_ids = (
        select(func.array_agg(func.distinct(actor_events.c.actor_id)))
        .where(actor_events.c.event_id == Event.id)
        .correlate(Event)
        .scalar_subquery()
    )
    stmt = select(
        Event.id,
        Event.event_date,
        Event.event_type,
        Event.fatalities,
        Event.geo_precision,
        func.ST_X(point),
        func.ST_Y(point),
        actor_ids,
    ).where(Event.geom.is_not(None))
    stmt = apply_filters(stmt, filters, session).order_by(Event.event_date).limit(MAX_POINTS + 1)
    rows = session.execute(stmt).all()
    truncated = len(rows) > MAX_POINTS
    features = [
        {
            "type": "Feature",
            "id": eid,
            "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
            "properties": {
                "id": eid,
                "d": d.isoformat(),
                "t": t,
                "f": f or 0,
                "gp": gp,
                "a": a or [],
            },
        }
        for eid, d, t, f, gp, x, y, a in rows[:MAX_POINTS]
    ]
    return {"type": "FeatureCollection", "features": features, "truncated": truncated}


class MonthCount(BaseModel):
    month: dt.date
    admin1_code: str | None
    events: int
    fatalities: int


@router.get("/timeseries", response_model=list[MonthCount])
def timeseries(session: DB, filters: Filters) -> list[MonthCount]:
    """Monthly event and fatality counts by admin1 (for the border panel)."""
    month = func.date_trunc("month", Event.event_date).label("month")
    stmt = select(
        month, Event.admin1_code, func.count(), func.coalesce(func.sum(Event.fatalities), 0)
    )
    stmt = apply_filters(stmt, filters, session).group_by(month, Event.admin1_code)
    rows = session.execute(stmt.order_by(month, Event.admin1_code)).all()
    return [
        MonthCount(
            month=m.date() if isinstance(m, dt.datetime) else m,
            admin1_code=a,
            events=n,
            fatalities=f,
        )
        for m, a, n, f in rows
    ]


class EventsMeta(BaseModel):
    total: int
    min_date: dt.date | None
    max_date: dt.date | None
    accessed: dt.datetime | None  # latest retrieval; ACLED attribution requires the access date
    sources: list[str]


@router.get("/meta", response_model=EventsMeta)
def events_meta(session: DB) -> EventsMeta:
    total, lo, hi, accessed = session.execute(
        select(
            func.count(),
            func.min(Event.event_date),
            func.max(Event.event_date),
            func.max(Event.retrieved_at),
        )
    ).one()
    slugs = session.scalars(
        select(Source.slug).where(Source.id.in_(select(Event.source_id).distinct()))
    ).all()
    return EventsMeta(
        total=total,
        min_date=lo,
        max_date=hi,
        accessed=accessed,
        sources=sorted(slugs),
    )


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, session: DB) -> EventOut:
    row = session.execute(event_select().where(Event.id == event_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "event not found")
    return event_out(row, actors_for(session, [event_id]), documents_for(session, [event_id]))
