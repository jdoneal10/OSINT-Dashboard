"""CBP border statistics (latest snapshot per month by default; ``as_of`` for history)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.db.models import BorderMetric, Node
from app.db.session import get_session

router = APIRouter(tags=["border"])
DB = Annotated[Session, Depends(get_session)]

Metric = Literal["encounters", "seizure_events", "seizure_lbs"]
GROUPABLE = ("component", "demographic", "citizenship", "encounter_type", "title", "drug_type")

CBP_NOTICE = (
    "Uses U.S. Customs and Border Protection public data; not endorsed by CBP. "
    "Figures are revised until fiscal-year close. Counts reflect enforcement activity and "
    "reporting, not total flow."
)


class SeriesPoint(BaseModel):
    month: dt.date
    group: str | None
    value: float


class MetricSeries(BaseModel):
    metric: str
    aor: list[str]
    unit: str | None
    group_by: str | None
    as_of: dt.date | None
    snapshots: list[dt.date]
    retrieved_at: dt.datetime | None
    notice: str = CBP_NOTICE
    series: list[SeriesPoint]


def _latest(
    metric: str,
    aor_ids: list[int],
    start: dt.date | None,
    end: dt.date | None,
    as_of: dt.date | None,
) -> Select[Any]:
    """One row per (aor, month, dimension_key): the newest snapshot on or before ``as_of``."""
    stmt = (
        select(BorderMetric)
        .where(BorderMetric.metric == metric, BorderMetric.aor_node_id.in_(aor_ids))
        .ext(distinct_on(BorderMetric.aor_node_id, BorderMetric.month, BorderMetric.dimension_key))
        .order_by(
            BorderMetric.aor_node_id,
            BorderMetric.month,
            BorderMetric.dimension_key,
            BorderMetric.snapshot_date.desc(),
        )
    )
    if start:
        stmt = stmt.where(BorderMetric.month >= start)
    if end:
        stmt = stmt.where(BorderMetric.month <= end)
    if as_of:
        stmt = stmt.where(BorderMetric.snapshot_date <= as_of)
    return stmt


def metric_series(
    session: Session,
    metric: str,
    aor: list[str],
    *,
    group_by: str | None,
    start: dt.date | None,
    end: dt.date | None,
    as_of: dt.date | None,
    where_dims: dict[str, list[str]] | None = None,
) -> MetricSeries:
    if group_by is not None and group_by not in GROUPABLE:
        raise HTTPException(422, f"group_by must be one of {GROUPABLE}")
    aor_ids = list(session.scalars(select(Node.id).where(Node.slug.in_(aor))))
    if len(aor_ids) != len(set(aor)):
        raise HTTPException(404, "unknown aor slug")
    latest = _latest(metric, aor_ids, start, end, as_of).subquery()
    group_col = latest.c.dimensions[group_by].astext if group_by else None
    cols = [
        latest.c.month,
        *([group_col.label("grp")] if group_col is not None else []),
        func.sum(latest.c.value),
    ]
    stmt = select(*cols).group_by(*cols[:-1]).order_by(*cols[:-1])
    for key, values in (where_dims or {}).items():
        stmt = stmt.where(latest.c.dimensions[key].astext.in_(values))
    rows = session.execute(stmt).all()
    meta = session.execute(
        select(
            func.array_agg(func.distinct(latest.c.snapshot_date)),
            func.max(latest.c.retrieved_at),
            func.max(latest.c.unit),
        )
    ).one()
    return MetricSeries(
        metric=metric,
        aor=aor,
        unit=meta[2],
        group_by=group_by,
        as_of=as_of,
        snapshots=sorted(meta[0] or []),
        retrieved_at=meta[1],
        series=[
            SeriesPoint(month=r[0], group=(r[1] if group_by else None), value=float(r[-1]))
            for r in rows
        ],
    )


@router.get("/border/metrics", response_model=MetricSeries)
def border_metrics(
    session: DB,
    metric: Metric,
    aor: Annotated[list[str], Query(description="node slugs, e.g. usbp-tucson")],
    group_by: str | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_of: dt.date | None = None,
    component: Annotated[list[str] | None, Query()] = None,
) -> MetricSeries:
    dims = {"component": component} if component else None
    return metric_series(
        session, metric, aor, group_by=group_by, start=start, end=end, as_of=as_of, where_dims=dims
    )


class SeizureSeries(BaseModel):
    aor: list[str]
    weight: MetricSeries
    events: MetricSeries


@router.get("/seizures", response_model=SeizureSeries)
def seizures(
    session: DB,
    aor: Annotated[list[str], Query()],
    drug_type: Annotated[list[str] | None, Query()] = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    as_of: dt.date | None = None,
) -> SeizureSeries:
    """CBP drug seizures by drug type and month (aggregates; event-level seizures: Phase 3)."""
    dims = {"drug_type": drug_type} if drug_type else None
    kw: dict[str, Any] = {
        "group_by": "drug_type",
        "start": start,
        "end": end,
        "as_of": as_of,
        "where_dims": dims,
    }
    return SeizureSeries(
        aor=aor,
        weight=metric_series(session, "seizure_lbs", aor, **kw),
        events=metric_series(session, "seizure_events", aor, **kw),
    )
