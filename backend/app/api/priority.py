"""Priority-topic panels (ADR 0009): unmanned systems and electricity theft.

Counts describe reported events only; they track what sources report, not underlying
activity. The escalation ladder applies the owner framework (owner judgment) to each event's
reported platform and payload; see ``app.analytics.priority``.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.priority import TopicSummary, energy_summary, uxs_summary
from app.db.session import get_session

router = APIRouter(prefix="/priority", tags=["priority"])
DB = Annotated[Session, Depends(get_session)]

CAVEAT = (
    "Counts of reported events, not of underlying activity: they rise and fall with source "
    "coverage and media attention."
)
LADDER_NOTE = (
    "Rungs derive from the owner framework (owner judgment) applied to each event's reported "
    "platform and payload. Rungs 6-8 have no extraction field yet and are not counted."
)


class MonthRow(BaseModel):
    month: str
    counts: dict[str, int]


class LadderOut(BaseModel):
    rung: int
    label: str
    captured: bool
    use: int
    capability: int
    first_seen: dt.date | None
    last_seen: dt.date | None


class TopicOut(BaseModel):
    total: int
    sources: int
    acled_events: int  # ACLED-derived events in the view (ACLED attribution required)
    months: list[MonthRow]
    breakdown: dict[str, dict[str, int]]
    states: dict[str, int]
    caveat: str = CAVEAT


class UxsOut(TopicOut):
    ladder: list[LadderOut]
    ladder_note: str = LADDER_NOTE


def _topic(s: TopicSummary) -> dict[str, object]:
    return {
        "total": s.total,
        "sources": s.sources,
        "acled_events": s.acled_events,
        "months": [MonthRow(month=m, counts=dict(c)) for m, c in sorted(s.months.items())],
        "breakdown": {k: dict(c.most_common()) for k, c in s.breakdown.items()},
        "states": dict(s.states.most_common()),
    }


@router.get("/uxs", response_model=UxsOut)
def uxs(
    session: DB,
    start: dt.date | None = None,
    end: dt.date | None = None,
    include_out_of_aoi: Annotated[bool, Query()] = False,
) -> UxsOut:
    s = uxs_summary(session, start, end, include_out_of_aoi)
    ladder = [LadderOut(**vars(row)) for row in s.ladder]
    return UxsOut(**_topic(s), ladder=ladder)


@router.get("/energy-theft", response_model=TopicOut)
def energy_theft(
    session: DB,
    start: dt.date | None = None,
    end: dt.date | None = None,
    include_out_of_aoi: Annotated[bool, Query()] = False,
) -> TopicOut:
    return TopicOut(**_topic(energy_summary(session, start, end, include_out_of_aoi)))
