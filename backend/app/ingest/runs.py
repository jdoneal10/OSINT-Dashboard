"""``ingest_runs`` bookkeeping: every job run is recorded, success or failure.

The run row is written in its own short transactions so a failed ingest still leaves an
audit record (also serves ACLED EULA s.15 record-keeping).

Closing a run must survive a database that is briefly unreachable (2026-11-23: the Docker
database timed out while the Mac woke from sleep, and run 6241 stayed "running"). The end
of a run is retried for about a minute; if it still cannot be written it is kept in memory
and retried by the worker's heartbeat (``flush_unfinished``). Each run records the process
that started it, so the worker closes runs whose process has ended (``close_orphaned_runs``).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.models import IngestRun, Source
from app.db.session import session_factory

log = logging.getLogger(__name__)

# Waits between attempts to record the end of a run (about a minute in all).
FINISH_RETRY_DELAYS = (5.0, 15.0, 40.0)
_sleep = time.sleep
# Ends of runs that could not be written yet: run id -> column values.
_UNFINISHED: dict[int, dict[str, Any]] = {}
INTERRUPTED = "interrupted: its process ended before the run recorded its end"


class UnknownSourceError(LookupError):
    """The source slug is not in the ``sources`` table (run ``make seed``)."""


class DeferredRun(Exception):  # noqa: N818 - a run outcome, not an error
    """Raised inside ``ingest_run`` when upstream refuses for now but nothing is lost: the
    next run's window covers this one (e.g. a GDELT 429 within the lookback). The run is
    recorded as ``deferred`` and the exception is not re-raised."""


def source_id(session: Session, slug: str) -> int:
    sid = session.scalar(select(Source.id).where(Source.slug == slug))
    if sid is None:
        raise UnknownSourceError(f"source {slug!r} not found; run `make seed` first")
    return sid


@dataclass
class RunContext:
    id: int
    job: str
    status: str = "running"
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


def misses_since_success(job: str) -> int:
    """Finished runs of ``job`` that were not ``ok``, since its last ``ok`` run."""
    with session_factory()() as session:
        last_ok = session.scalar(
            select(IngestRun.finished_at)
            .where(IngestRun.job == job, IngestRun.status == "ok")
            .order_by(IngestRun.finished_at.desc())
            .limit(1)
        )
        query = select(func.count()).where(
            IngestRun.job == job, IngestRun.status.in_(("deferred", "error"))
        )
        if last_ok is not None:
            query = query.where(IngestRun.finished_at > last_ok)
        return session.scalar(query) or 0


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
        run = IngestRun(
            job=job, source_id=sid, status="running", params=params or {}, pid=os.getpid()
        )
        session.add(run)
        session.flush()
        ctx = RunContext(id=run.id, job=job, params=dict(params or {}))

    status, error = "ok", None
    try:
        yield ctx
    except DeferredRun as exc:
        status, error = "deferred", redact(str(exc))[:4000]
        log.warning("job %s (run %d) deferred: %s", job, ctx.id, error)
    except BaseException as exc:
        status, error = "error", redact(f"{type(exc).__name__}: {exc}")[:4000]
        log.error("job %s (run %d) failed: %s", job, ctx.id, error)
        raise
    finally:
        _finish(
            ctx.id,
            {
                "status": status,
                "error": error,
                "finished_at": dt.datetime.now(dt.UTC),
                "rows_inserted": ctx.inserted,
                "rows_updated": ctx.updated,
                "rows_deleted": ctx.deleted,
                "params": ctx.params,
                "raw_path": "\n".join(ctx.raw_paths) or None,
            },
        )
        ctx.status = status
        log.info(
            "job %s (run %d) %s: +%d ~%d -%d",
            job,
            ctx.id,
            status,
            ctx.inserted,
            ctx.updated,
            ctx.deleted,
        )


def _write_end(run_id: int, values: dict[str, Any]) -> None:
    with session_factory()() as session, session.begin():
        run = session.get_one(IngestRun, run_id)
        for key, value in values.items():
            setattr(run, key, value)


def _finish(run_id: int, values: dict[str, Any]) -> None:
    """Record the end of a run, retrying while the database is unreachable. Never raises for
    an unreachable database: the end is kept for ``flush_unfinished`` instead."""
    for delay in (*FINISH_RETRY_DELAYS, None):
        try:
            _write_end(run_id, values)
            return
        except OperationalError as exc:
            if delay is None:
                _UNFINISHED[run_id] = values
                log.error(
                    "could not record the end of run %d (%s); retrying at the next heartbeat",
                    run_id,
                    redact(str(exc).splitlines()[0])[:200],
                )
                return
            _sleep(delay)


def flush_unfinished() -> int:
    """Write the ends of runs that could not be recorded earlier. Returns how many were."""
    written = 0
    for run_id, values in list(_UNFINISHED.items()):
        try:
            _write_end(run_id, values)
        except OperationalError:
            break  # still unreachable; the next heartbeat tries again
        del _UNFINISHED[run_id]
        written += 1
        log.info("recorded the end of run %d (%s)", run_id, values["status"])
    return written


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def close_orphaned_runs() -> list[int]:
    """Close "running" rows whose process has ended, as errors (run when the worker starts).

    Rows from before the process was recorded (``pid`` NULL, migration 0021) are closed too:
    their processes cannot be checked, and none of them is still running.
    """
    now = dt.datetime.now(dt.UTC)
    closed: list[int] = []
    with session_factory()() as session, session.begin():
        for run in session.scalars(select(IngestRun).where(IngestRun.status == "running")):
            if run.pid is not None and (run.pid == os.getpid() or _alive(run.pid)):
                continue
            run.status, run.error, run.finished_at = "error", INTERRUPTED, now
            closed.append(run.id)
    if closed:
        log.warning("closed %d run(s) left running by ended processes: %s", len(closed), closed)
    return closed
