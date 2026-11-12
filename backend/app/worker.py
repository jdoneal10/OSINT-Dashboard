"""Scheduler entrypoint: heartbeat plus scheduled source pulls (times in UTC).

- heartbeat: every N minutes; liveness row in ingest_runs (shown in /health)
- acled-events: daily 11:00; ACLED incremental pull since the last watermark
- acled-deleted: Sundays 11:30; ACLED deleted-events reconciliation (weekly upstream)
- cbp: daily 12:00; two page checks, ingests only when a new CBP file appears
- news-feeds: hourly at :05; RSS and listing-page feeds in data/reference/feeds.yaml
- news-gdelt: every 3 hours at :20; GDELT DOC queries for outlets without RSS
- pipeline: every 30 minutes at :10/:40; dedupe, local filter, Haiku extract, cluster,
  Admiralty, Sonnet analyze. The Claude gateway checks the monthly budget before every call
  and pauses the API stages at the threshold; the local stages keep running.
- designations: daily 13:00; OFAC SDN (skipped when unchanged) and Federal Register notices
- sesnsp-reminder: monthly on the 26th; SESNSP blocks automated downloads, so an alert asks
  the owner to download the new municipal file when the newest snapshot is > 40 days old

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
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Alert, CrimeIncidence, IngestRun
from app.db.session import session_factory
from app.enrich import pipeline
from app.ingest import acled, cbp, designations, feeds, news

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


SESNSP_STALE_DAYS = 40


def news_feeds() -> int:
    """RSS and listing-page feeds (GDELT-discovered outlets run on their own schedule)."""
    return news.run_news([f.slug for f in feeds.active() if f.discovery != "gdelt"])


def news_gdelt() -> int:
    slugs = [f.slug for f in feeds.active("gdelt")]
    return news.run_news(slugs) if slugs else 0


def run_pipeline() -> dict[str, object]:
    return pipeline.run_pipeline()


def sesnsp_reminder(today: dt.date | None = None) -> bool:
    """Raise one alert per month when the newest SESNSP snapshot is stale. Returns True if
    an alert was written."""
    today = today or dt.datetime.now(dt.UTC).date()
    month = today.strftime("%Y-%m")
    with session_factory()() as session, session.begin():
        latest = session.scalar(select(func.max(CrimeIncidence.snapshot_date)))
        if latest is not None and (today - latest).days <= SESNSP_STALE_DAYS:
            return False
        exists = session.scalar(
            select(func.count()).where(
                Alert.rule == "sesnsp_update_due", Alert.linked_records["month"].astext == month
            )
        )
        if exists:
            return False
        session.add(
            Alert(
                rule="sesnsp_update_due",
                severity=1,
                summary=(
                    "New SESNSP municipal crime data is likely available "
                    f"(newest snapshot: {latest or 'none'}). Download the municipal file "
                    "and run: make ingest SOURCE=sesnsp FILE=<path>"
                ),
                linked_records={"month": month, "latest_snapshot": str(latest or "")},
            )
        )
    log.info("SESNSP update reminder raised")
    return True


SCHEDULED_JOBS: list[tuple[str, Callable[[], object], CronTrigger]] = [
    ("acled-events", acled.run_events, CronTrigger(hour=11, minute=0, timezone="UTC")),
    (
        "acled-deleted",
        acled.run_deleted,
        CronTrigger(day_of_week="sun", hour=11, minute=30, timezone="UTC"),
    ),
    ("cbp", cbp.run_remote, CronTrigger(hour=12, minute=0, timezone="UTC")),
    ("news-feeds", news_feeds, CronTrigger(minute=5, timezone="UTC")),
    ("news-gdelt", news_gdelt, CronTrigger(hour="*/3", minute=20, timezone="UTC")),
    ("pipeline", run_pipeline, CronTrigger(minute="10,40", timezone="UTC")),
    ("designations", designations.run_designations, CronTrigger(hour=13, minute=0, timezone="UTC")),
    ("sesnsp-reminder", sesnsp_reminder, CronTrigger(day=26, hour=14, minute=0, timezone="UTC")),
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
