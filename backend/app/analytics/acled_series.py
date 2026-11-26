"""One continuous weekly ACLED series: historical events joined with weekly aggregates.

ADR 0011. The grain is ACLED's week (Saturday to Friday, keyed by the Saturday) x admin1 x
event type. Each week takes its counts from exactly one source:

- ``events``: ACLED event records rolled up, for every week that ends on or before the
  *event horizon*. ACLED releases event data with a lag and the newest released week is
  usually partial (2026-11-16: the week of 2025-11-08 had 183 events released of 322), so
  the horizon is the last Friday at least a week before the newest event date.
- ``aggregate``: the weekly aggregate files, for weeks after the horizon. Each week comes
  whole from the newest snapshot that covers it, so a short update file (the owner's
  two-week downloads) extends the series instead of replacing it, and a newer full file
  supersedes older ones week by week.

When no aggregate snapshot is loaded, events are used for every week, including the partial
last one. When ACLED releases more events, the horizon moves and events take those weeks
over automatically; aggregate snapshots stay in the table as history.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Date, Integer, cast, func, literal, select
from sqlalchemy.orm import Session

from app.db.models import AcledWeekly, Event, Source

EVENT_SOURCE = "acled"
Origin = Literal["events", "aggregate"]


@dataclass(frozen=True)
class WeekRow:
    week: dt.date
    admin1_code: str
    event_type: str
    events: int
    fatalities: int
    origin: Origin


@dataclass(frozen=True)
class SeriesMeta:
    events_through: dt.date | None  # newest ACLED event date
    horizon_week_end: dt.date | None  # last week (Friday) taken from events
    aggregate_snapshot: dt.date | None
    aggregate_first_week: dt.date | None
    aggregate_last_week: dt.date | None
    events_accessed: dt.datetime | None
    aggregate_accessed: dt.datetime | None


def week_start(day: dt.date) -> dt.date:
    """The Saturday that starts ACLED's week containing ``day``."""
    return day - dt.timedelta(days=(day.weekday() - 5) % 7)


def _acled_week(column: Any) -> Any:
    """SQL: the Saturday on or before ``column`` (Postgres dow: Sunday=0 ... Saturday=6)."""
    offset = (cast(func.extract("dow", column), Integer) + 1) % 7
    return cast(column - offset * literal(dt.timedelta(days=1)), Date)


def _latest_snapshot(session: Session) -> dt.date | None:
    return session.scalar(select(func.max(AcledWeekly.snapshot_date)))


def series_meta(session: Session) -> SeriesMeta:
    through, accessed = session.execute(
        select(func.max(Event.event_date), func.max(Event.retrieved_at))
        .join(Source, Source.id == Event.source_id)
        .where(Source.slug == EVENT_SOURCE)
    ).one()
    snap = _latest_snapshot(session)
    first = last = agg_accessed = None
    if snap is not None:  # weeks across all snapshots: each week reads its newest one
        first, last, agg_accessed = session.execute(
            select(
                func.min(AcledWeekly.week),
                func.max(AcledWeekly.week),
                func.max(AcledWeekly.retrieved_at),
            )
        ).one()
    horizon = None
    if through is not None:
        # the last Friday at least a week before the newest event: the newest released
        # week is usually partial, so it is left to the aggregates
        margin = through - dt.timedelta(days=7)
        horizon = margin - dt.timedelta(days=(margin.weekday() - 4) % 7)
        if snap is None:
            horizon = week_start(through) + dt.timedelta(days=6)
    return SeriesMeta(
        events_through=through,
        horizon_week_end=horizon,
        aggregate_snapshot=snap,
        aggregate_first_week=first,
        aggregate_last_week=last,
        events_accessed=accessed,
        aggregate_accessed=agg_accessed,
    )


def _filters(
    week: Any,
    admin1_col: Any,
    type_col: Any,
    *,
    admin1: list[str] | None,
    event_type: list[str] | None,
    start: dt.date | None,
    end: dt.date | None,
) -> list[Any]:
    """WHERE clauses shared by both sources; ``start``/``end`` select weeks by Saturday."""
    clauses: list[Any] = []
    if admin1:
        clauses.append(admin1_col.in_(admin1))
    if event_type:
        clauses.append(type_col.in_(event_type))
    if start:
        clauses.append(week >= week_start(start))
    if end:
        clauses.append(week <= week_start(end))
    return clauses


def weekly_series(
    session: Session,
    *,
    admin1: list[str] | None = None,
    event_type: list[str] | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    meta: SeriesMeta | None = None,
) -> list[WeekRow]:
    """Weekly counts per admin1 and event type, ordered by week. ``start``/``end`` select
    weeks by their Saturday."""
    meta = meta or series_meta(session)
    horizon_start = meta.horizon_week_end - dt.timedelta(days=6) if meta.horizon_week_end else None
    rows: list[WeekRow] = []

    week = _acled_week(Event.event_date).label("week")
    ev = (
        select(
            week,
            Event.admin1_code,
            Event.event_type,
            func.count(),
            func.coalesce(func.sum(Event.fatalities), 0),
        )
        .join(Source, Source.id == Event.source_id)
        .where(Source.slug == EVENT_SOURCE, Event.admin1_code.is_not(None))
        .group_by(week, Event.admin1_code, Event.event_type)
    )
    if horizon_start is not None:
        ev = ev.where(week <= horizon_start)
    ev = ev.where(
        *_filters(
            week,
            Event.admin1_code,
            Event.event_type,
            admin1=admin1,
            event_type=event_type,
            start=start,
            end=end,
        )
    )
    for w, a, t, n, f in session.execute(ev):
        rows.append(WeekRow(w, a, t, int(n), int(f), "events"))

    if meta.aggregate_snapshot is not None:
        newest = (
            select(AcledWeekly.week, func.max(AcledWeekly.snapshot_date).label("snap"))
            .group_by(AcledWeekly.week)
            .subquery()
        )
        agg = (
            select(
                AcledWeekly.week,
                AcledWeekly.admin1_code,
                AcledWeekly.event_type,
                func.sum(AcledWeekly.events),
                func.sum(AcledWeekly.fatalities),
            )
            .join(
                newest,
                (newest.c.week == AcledWeekly.week) & (newest.c.snap == AcledWeekly.snapshot_date),
            )
            .group_by(AcledWeekly.week, AcledWeekly.admin1_code, AcledWeekly.event_type)
        )
        if horizon_start is not None:
            agg = agg.where(AcledWeekly.week > horizon_start)
        agg = agg.where(
            *_filters(
                AcledWeekly.week,
                AcledWeekly.admin1_code,
                AcledWeekly.event_type,
                admin1=admin1,
                event_type=event_type,
                start=start,
                end=end,
            )
        )
        for w, a, t, n, f in session.execute(agg):
            rows.append(WeekRow(w, a, t, int(n), int(f), "aggregate"))

    rows.sort(key=lambda r: (r.week, r.admin1_code, r.event_type))
    return rows
