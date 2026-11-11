from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.db.models import IngestRun
from app.db.session import get_session

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    db: Literal["ok", "error"]
    postgis_version: str | None = None
    worker_last_heartbeat: dt.datetime | None = None


@router.get("/health", response_model=Health)
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> Health:
    try:
        postgis = session.execute(text("SELECT postgis_lib_version()")).scalar_one()
        heartbeat = session.scalar(
            select(func.max(IngestRun.finished_at)).where(IngestRun.job == "heartbeat")
        )
    except SQLAlchemyError:
        log.exception("health check: database unreachable")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="degraded", version=__version__, db="error")
    return Health(
        status="ok",
        version=__version__,
        db="ok",
        postgis_version=str(postgis),
        worker_last_heartbeat=heartbeat,
    )
