"""SESNSP municipal crime incidence (choropleth data).

SESNSP changed methodology in 2026; 2015-2025 and 2026+ figures are not comparable, so a
request whose month range spans both is rejected. Only the latest snapshot of each
methodology is served (earlier snapshots stay in the table as history).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CrimeIncidence, ReferenceArea
from app.db.session import get_session

router = APIRouter(prefix="/crime-incidence", tags=["crime-incidence"])
DB = Annotated[Session, Depends(get_session)]


def _latest() -> Any:
    """(methodology, snapshot_date) of the newest snapshot per methodology."""
    return (
        select(CrimeIncidence.methodology, func.max(CrimeIncidence.snapshot_date).label("snap"))
        .group_by(CrimeIncidence.methodology)
        .subquery()
    )


def _current() -> Any:
    latest = _latest()
    return select(CrimeIncidence).join(
        latest,
        (latest.c.methodology == CrimeIncidence.methodology)
        & (latest.c.snap == CrimeIncidence.snapshot_date),
    )


class MethodologyMeta(BaseModel):
    methodology: str
    snapshot_date: dt.date
    first_month: dt.date
    last_month: dt.date
    crime_types: list[str]


@router.get("/meta", response_model=list[MethodologyMeta])
def crime_meta(session: DB) -> list[MethodologyMeta]:
    cur = _current().subquery()
    rows = session.execute(
        select(
            cur.c.methodology,
            func.max(cur.c.snapshot_date),
            func.min(cur.c.month),
            func.max(cur.c.month),
            func.array_agg(func.distinct(cur.c.crime_type)),
        ).group_by(cur.c.methodology)
    ).all()
    return [
        MethodologyMeta(
            methodology=m, snapshot_date=s, first_month=a, last_month=b, crime_types=sorted(t)
        )
        for m, s, a, b, t in sorted(rows)
    ]


class MunicipalValue(BaseModel):
    admin2_code: str
    admin1_code: str
    name: str | None
    value: int


class CrimeChoropleth(BaseModel):
    methodology: str
    snapshot_date: dt.date
    crime_type: str
    start: dt.date
    end: dt.date
    items: list[MunicipalValue]


def _month(d: dt.date) -> dt.date:
    return d.replace(day=1)


@router.get("", response_model=CrimeChoropleth)
def crime_by_municipality(
    session: DB,
    crime_type: Annotated[str, Query(description="e.g. Homicidio; see /crime-incidence/meta")],
    start: Annotated[dt.date, Query(description="first month (any day in it)")],
    end: Annotated[dt.date | None, Query(description="last month; default = start")] = None,
    admin1: Annotated[list[str] | None, Query(description="e.g. MX-SIN")] = None,
) -> CrimeChoropleth:
    """Victim/incident counts summed per municipality over the month range (nonzero only)."""
    lo, hi = _month(start), _month(end or start)
    if hi < lo:
        raise HTTPException(422, "end is before start")
    cur = _current().where(
        CrimeIncidence.crime_type == crime_type,
        CrimeIncidence.month >= lo,
        CrimeIncidence.month <= hi,
    )
    if admin1:
        cur = cur.where(CrimeIncidence.admin1_code.in_(admin1))
    sub = cur.subquery()
    methods = session.execute(
        select(sub.c.methodology, func.max(sub.c.snapshot_date)).group_by(sub.c.methodology)
    ).all()
    if len(methods) > 1:
        raise HTTPException(
            422, "range spans SESNSP methodologies 2015-2025 and 2026, which are not comparable"
        )
    if not methods:
        raise HTTPException(404, "no data for this crime type and range")
    ((methodology, snapshot),) = methods
    names = (
        select(ReferenceArea.name)
        .where(ReferenceArea.area_type == "admin2", ReferenceArea.admin2_code == sub.c.admin2_code)
        .limit(1)
        .scalar_subquery()
    )
    rows = session.execute(
        select(sub.c.admin2_code, sub.c.admin1_code, names, func.sum(sub.c.value))
        .group_by(sub.c.admin2_code, sub.c.admin1_code)
        .order_by(func.sum(sub.c.value).desc())
    ).all()
    return CrimeChoropleth(
        methodology=methodology,
        snapshot_date=snapshot,
        crime_type=crime_type,
        start=lo,
        end=hi,
        items=[
            MunicipalValue(admin2_code=a2, admin1_code=a1, name=n, value=int(v))
            for a2, a1, n, v in rows
        ],
    )
