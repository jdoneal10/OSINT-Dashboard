"""LLM spend against the monthly cap (header budget indicator)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LLMQuarantine, LLMUsage
from app.db.session import get_session
from app.enrich.llm.client import budget_status, month_start

router = APIRouter(prefix="/llm", tags=["llm"])
DB = Annotated[Session, Depends(get_session)]


class StageSpend(BaseModel):
    stage: str
    model: str
    calls: int
    cost_usd: float


class LLMUsageOut(BaseModel):
    month: dt.date
    spent_usd: float
    cap_usd: float
    pause_threshold_usd: float
    paused: bool
    calls: int
    failed_calls: int
    quarantined: int
    by_stage: list[StageSpend]


@router.get("/usage", response_model=LLMUsageOut)
def llm_usage(session: DB) -> LLMUsageOut:
    start = month_start()
    status = budget_status(session)
    rows = session.execute(
        select(LLMUsage.stage, LLMUsage.model, func.count(), func.sum(LLMUsage.cost_usd))
        .where(LLMUsage.called_at >= start)
        .group_by(LLMUsage.stage, LLMUsage.model)
        .order_by(func.sum(LLMUsage.cost_usd).desc())
    ).all()
    failed = session.scalar(
        select(func.count()).where(LLMUsage.called_at >= start, LLMUsage.status != "ok")
    )
    quarantined = session.scalar(select(func.count()).where(LLMQuarantine.created_at >= start))
    return LLMUsageOut(
        month=start.date(),
        spent_usd=float(status["spent"]),
        cap_usd=float(status["cap"]),
        pause_threshold_usd=float(status["threshold"]),
        paused=bool(status["paused"]),
        calls=sum(n for _, _, n, _ in rows),
        failed_calls=failed or 0,
        quarantined=quarantined or 0,
        by_stage=[
            StageSpend(stage=s, model=m, calls=n, cost_usd=float(c or 0)) for s, m, n, c in rows
        ],
    )
