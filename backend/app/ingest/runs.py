"""``ingest_runs`` bookkeeping: every job run is recorded, success or failure.

The run row is written in its own short transactions so a failed ingest still leaves an
audit record (also serves ACLED EULA s.15 record-keeping).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.models import IngestRun, Source
from app.db.session import session_factory

log = logging.getLogger(__name__)


class UnknownSourceError(LookupError):
    """The source slug is not in the ``sources`` table (run ``make seed``)."""


def source_id(session: Session, slug: str) -> int:
    sid = session.scalar(select(Source.id).where(Source.slug == slug))
    if sid is None:
        raise UnknownSourceError(f"source {slug!r} not found; run `make seed` first")
    return sid


@dataclass
class RunContext:
    id: int
    job: str
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    params: dict[str, Any] = field(default_factory=dict)
    raw_paths: list[str] = field(default_factory=list)


def last_successful_params(job: str) -> dict[str, Any] | None:
    with session_factory()() as session:
        params: dict[str, Any] | None = session.scalar(
            select(IngestRun.params)
            .where(IngestRun.job == job, IngestRun.status == "ok")
            .order_by(IngestRun.finished_at.desc())
            .limit(1)
        )
    return params


def file_already_ingested(job: str, sha256: str) -> bool:
    """True if a successful run of ``job`` already recorded this file hash."""
    with session_factory()() as session:
        hit = session.scalar(
            select(IngestRun.id)
            .where(
                IngestRun.job == job,
                IngestRun.status == "ok",
                IngestRun.params["files"].contains([{"sha256": sha256}]),
            )
            .limit(1)
        )
    return hit is not None


@contextmanager
def ingest_run(
    job: str, *, source_slug: str | None = None, params: dict[str, Any] | None = None
) -> Iterator[RunContext]:
    factory = session_factory()
    with factory() as session, session.begin():
        sid = source_id(session, source_slug) if source_slug else None
        run = IngestRun(job=job, source_id=sid, status="running", params=params or {})
        session.add(run)
        session.flush()
        ctx = RunContext(id=run.id, job=job, params=dict(params or {}))

    status, error = "ok", None
    try:
        yield ctx
    except BaseException as exc:
        status, error = "error", redact(f"{type(exc).__name__}: {exc}")[:4000]
        log.error("job %s (run %d) failed: %s", job, ctx.id, error)
        raise
    finally:
        with factory() as session, session.begin():
            run = session.get_one(IngestRun, ctx.id)
            run.status = status
            run.error = error
            run.finished_at = dt.datetime.now(dt.UTC)
            run.rows_inserted = ctx.inserted
            run.rows_updated = ctx.updated
            run.rows_deleted = ctx.deleted
            run.params = ctx.params
            run.raw_path = "\n".join(ctx.raw_paths) or None
        log.info(
            "job %s (run %d) %s: +%d ~%d -%d",
            job,
            ctx.id,
            status,
            ctx.inserted,
            ctx.updated,
            ctx.deleted,
        )
