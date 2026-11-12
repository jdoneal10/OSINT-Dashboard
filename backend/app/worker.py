"""Scheduler entrypoint: heartbeat plus scheduled source pulls (times in UTC).

- heartbeat: every N minutes; liveness row in ingest_runs (shown in /health)
- acled-events: daily 11:00; ACLED incremental pull since the last watermark
- acled-deleted: Sundays 11:30; ACLED deleted-events reconciliation (weekly upstream)
- cbp: daily 12:00; two page checks, ingests only when a new CBP file appears

A failing job is logged (and recorded in ingest_runs when it got that far) and never
stops the scheduler. Set OSINT_SCHEDULED_INGEST=false to run the heartbeat only.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import signal
from collections.abc import Callable
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import IngestRun
from app.db.session import session_factory
from app.ingest import acled, cbp

log = logging.getLogger("app.worker")


def heartbeat() -> None:
    now = dt.datetime.now(dt.UTC)
    with session_factory()() as session, session.begin():
        session.add(IngestRun(job="heartbeat", started_at=now, finished_at=now, status="ok"))
    log.info("heartbeat")


def _guarded(name: str, fn: Callable[[], object]) -> Callable[[], None]:
    def run() -> None:
        try:
            fn()
        except Exception:
            log.exception("scheduled job %s failed", name)

    run.__name__ = f"job_{name.replace('-', '_')}"
    return run


SCHEDULED_JOBS: list[tuple[str, Callable[[], object], CronTrigger]] = [
    ("acled-events", acled.run_events, CronTrigger(hour=11, minute=0, timezone="UTC")),
    (
        "acled-deleted",
        acled.run_deleted,
        CronTrigger(day_of_week="sun", hour=11, minute=30, timezone="UTC"),
    ),
    ("cbp", cbp.run_remote, CronTrigger(hour=12, minute=0, timezone="UTC")),
]


def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        heartbeat,
        "interval",
        minutes=settings.worker_heartbeat_minutes,
        id="heartbeat",
        next_run_time=dt.datetime.now(dt.UTC),
        coalesce=True,
        max_instances=1,
    )
    if settings.scheduled_ingest:
        for name, fn, trigger in SCHEDULED_JOBS:
            scheduler.add_job(
                _guarded(name, fn),
                trigger,
                id=name,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )
    return scheduler


def main() -> None:
    configure_logging(get_settings().log_level)
    scheduler = build_scheduler()

    def _stop(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d; shutting down", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _stop)
    log.info("worker started; jobs: %s", [job.id for job in scheduler.get_jobs()])
    with contextlib.suppress(KeyboardInterrupt):
        scheduler.start()


if __name__ == "__main__":
    main()
