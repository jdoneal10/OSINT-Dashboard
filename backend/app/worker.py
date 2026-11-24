"""Scheduler entrypoint: heartbeat plus scheduled source pulls (times in UTC).

- heartbeat: every N minutes; liveness row in ingest_runs (shown in /health); also records
  run ends that an unreachable database kept from being written (app.ingest.runs)
- acled-events: daily 11:00; ACLED incremental pull since the last watermark
- acled-deleted: Sundays 11:30; ACLED deleted-events reconciliation (weekly upstream)
- cbp: daily 12:00; two page checks, ingests only when a new CBP file appears
- news-feeds: hourly at :05; RSS and listing-page feeds in data/reference/feeds.yaml
- news-gdelt: every 6 hours at :20; GDELT DOC queries for outlets without RSS, one feed
  at a time, up to 30 minutes apart and spaced so the cycle ends within the 6 hours
- pipeline: every 30 minutes at :10/:40; dedupe, local filter, Haiku extract, cluster,
  Admiralty, Sonnet analyze. The Claude gateway checks the monthly budget before every call
  and pauses the API stages at the threshold; the local stages keep running.
- designations: daily 13:00; OFAC SDN (skipped when unchanged) and Federal Register notices
- sesnsp-reminder: monthly on the 26th; SESNSP blocks automated downloads, so an alert asks
  the owner to download the new municipal file when the newest snapshot is > 40 days old

A failing job is logged (and recorded in ingest_runs when it got that far) and never
stops the scheduler; one failing GDELT feed never stops the others. On start, runs left
"running" by ended processes are closed as errors. Set OSINT_SCHEDULED_INGEST=false to run
the heartbeat only.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import signal
import time
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
from app.ingest import acled, cbp, dataminr, designations, feeds, news, runs

log = logging.getLogger("app.worker")


def heartbeat() -> None:
    runs.flush_unfinished()
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


GDELT_CYCLE_S = 6 * 60 * 60  # the news-gdelt trigger interval
GDELT_CYCLE_MARGIN_S = 15 * 60
# A refused feed takes about 8.5 minutes: five tries 30 s, 1, 2 and 4 min apart.
GDELT_FEED_WORST_S = 10 * 60
GDELT_FEED_SPACING_MAX_S = 30 * 60
GDELT_FEED_SPACING_MIN_S = 5 * 60


def gdelt_spacing(n_feeds: int) -> float:
    """Seconds between GDELT feeds: at most 30 minutes, and short enough that a cycle where
    every feed is refused still ends before the next trigger. A cycle that ran past 6 hours
    made the scheduler skip the next one, so each feed ran every 12 hours (2026-11-24)."""
    if n_feeds < 2:
        return 0.0
    budget = GDELT_CYCLE_S - GDELT_CYCLE_MARGIN_S - n_feeds * GDELT_FEED_WORST_S
    spacing = budget / (n_feeds - 1)
    return float(max(GDELT_FEED_SPACING_MIN_S, min(GDELT_FEED_SPACING_MAX_S, spacing)))


def news_gdelt(sleep: Callable[[float], None] = time.sleep) -> int:
    """One GDELT feed at a time, ``gdelt_spacing`` apart. A feed that fails outside its own
    run (for example the database unreachable before it starts) is logged and the next feed
    still runs."""
    rc = 0
    slugs = [f.slug for f in feeds.active("gdelt")]
    spacing = gdelt_spacing(len(slugs))
    for i, slug in enumerate(slugs):
        if i:
            sleep(spacing)
        try:
            rc |= news.run_news([slug])
        except Exception:
            rc |= 1
            log.exception("GDELT feed %s failed; continuing with the next feed", slug)
    return rc


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
    ("news-gdelt", news_gdelt, CronTrigger(hour="*/6", minute=20, timezone="UTC")),
    # Dataminr digests land in data/raw/dataminr/inbox/ from the owner's Gmail connector at
    # 09:00 HST (ADR 0012); one daily check an hour later feeds the 20:10 UTC pipeline pass.
    ("dataminr", dataminr.run_inbox, CronTrigger(hour=10, minute=0, timezone="Pacific/Honolulu")),
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
    try:
        runs.close_orphaned_runs()
    except Exception:
        log.exception("could not close runs left running by ended processes")
    log.info("worker started; jobs: %s", [job.id for job in scheduler.get_jobs()])
    with contextlib.suppress(KeyboardInterrupt):
        scheduler.start()


if __name__ == "__main__":
    main()
