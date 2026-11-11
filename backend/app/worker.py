"""Scheduler entrypoint. Phase 0 runs only a heartbeat; source pulls arrive in Phase 1."""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import signal
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import IngestRun
from app.db.session import session_factory

log = logging.getLogger("app.worker")


def heartbeat() -> None:
    now = dt.datetime.now(dt.UTC)
    with session_factory()() as session, session.begin():
        session.add(IngestRun(job="heartbeat", started_at=now, finished_at=now, status="ok"))
    log.info("heartbeat")


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
