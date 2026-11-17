"""Combined weekly ACLED series: historical events joined with ACLED's weekly aggregates.

ADR 0011. Weeks run Saturday to Friday and are keyed by the Saturday. Each week comes from
one source only (``origin``): event records up to the event horizon, aggregates after it.
The aggregates have no individual events, so the event map, event list and corroboration
stay event-level; these endpoints feed trend charts and state choropleths only.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.acled_series import Origin, SeriesMeta, series_meta, weekly_series
from app.db.session import get_session

router = APIRouter(prefix="/acled/weekly", tags=["acled"])
DB = Annotated[Session, Depends(get_session)]
Admin1 = Annotated[list[str] | None, Query(description="e.g. MX-SIN")]
EventType = Annotated[list[str] | None, Query(description="ACLED event type")]


class WeeklyMeta(BaseModel):
    events_through: dt.date | None
    horizon_week_end: dt.date | None
    aggregate_snapshot: dt.date | None
    aggregate_first_week: dt.date | None
    aggregate_last_week: dt.date | None
    events_accessed: dt.datetime | None
    aggregate_accessed: dt.datetime | None


def _meta(m: SeriesMeta) -> WeeklyMeta:
    return WeeklyMeta(**m.__dict__)


@router.get("/meta", response_model=WeeklyMeta)
def meta(session: DB) -> WeeklyMeta:
    return _meta(series_meta(session))


class WeekPoint(BaseModel):
    week: dt.date
    events: int
    fatalities: int
    origin: Origin


class WeeklySeries(BaseModel):
    meta: WeeklyMeta
    points: list[WeekPoint]


@router.get("", response_model=WeeklySeries)
def series(
    session: DB,
    admin1: Admin1 = None,
    event_type: EventType = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> WeeklySeries:
    """Weekly totals over the selected states and event types."""
    m = series_meta(session)
    totals: dict[dt.date, list[int]] = defaultdict(lambda: [0, 0])
    origin: dict[dt.date, Origin] = {}
    for row in weekly_series(
        session, admin1=admin1, event_type=event_type, start=start, end=end, meta=m
    ):
        totals[row.week][0] += row.events
        totals[row.week][1] += row.fatalities
        origin[row.week] = row.origin
    points = [
        WeekPoint(week=w, events=n, fatalities=f, origin=origin[w])
        for w, (n, f) in sorted(totals.items())
    ]
    return WeeklySeries(meta=_meta(m), points=points)


class StateTotal(BaseModel):
    admin1_code: str
    events: int
    fatalities: int


class StateTotals(BaseModel):
    meta: WeeklyMeta
    start: dt.date | None
    end: dt.date | None
    origins: list[Origin]
    items: list[StateTotal]


@router.get("/states", response_model=StateTotals)
def states(
    session: DB,
    event_type: EventType = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> StateTotals:
    """Totals per state over a week range (choropleth)."""
    m = series_meta(session)
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    origins: set[Origin] = set()
    for row in weekly_series(session, event_type=event_type, start=start, end=end, meta=m):
        totals[row.admin1_code][0] += row.events
        totals[row.admin1_code][1] += row.fatalities
        origins.add(row.origin)
    items = [StateTotal(admin1_code=a, events=n, fatalities=f) for a, (n, f) in totals.items()]
    return StateTotals(
        meta=_meta(m),
        start=start,
        end=end,
        origins=sorted(origins),
        items=sorted(items, key=lambda i: i.admin1_code),
    )
