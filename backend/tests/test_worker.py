from __future__ import annotations

import datetime as dt
import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import worker
from app.core.config import get_settings
from app.db.models import Alert, CrimeIncidence, Source


def test_scheduler_registers_source_jobs() -> None:
    scheduler = worker.build_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {
        "heartbeat", "acled-events", "acled-deleted", "cbp", "news-feeds", "news-gdelt",
        "dataminr", "pipeline", "designations", "sesnsp-reminder",
    }  # fmt: skip
    assert "hour='11'" in str(jobs["acled-events"].trigger)
    assert "day_of_week='sun'" in str(jobs["acled-deleted"].trigger)
    assert "minute='10,40'" in str(jobs["pipeline"].trigger)
    assert "hour='*/6'" in str(jobs["news-gdelt"].trigger)
    # Once a day, an hour after the owner's 09:00 HST connector run (ADR 0012).
    dataminr_trigger = jobs["dataminr"].trigger
    assert str(dataminr_trigger.timezone) == "Pacific/Honolulu"
    nxt = dataminr_trigger.get_next_fire_time(None, dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC))
    assert nxt == dt.datetime(2026, 11, 22, 20, tzinfo=dt.UTC)
    later = dataminr_trigger.get_next_fire_time(nxt, nxt + dt.timedelta(minutes=1))
    assert later - nxt == dt.timedelta(days=1)


def test_scheduled_ingest_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "scheduled_ingest", False)
    assert [j.id for j in worker.build_scheduler().get_jobs()] == ["heartbeat"]


def test_failing_job_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        raise RuntimeError("upstream down")

    with caplog.at_level(logging.ERROR):
        worker._guarded("test-job", boom)()
    assert "scheduled job test-job failed" in caplog.text


def test_news_jobs_split_feeds_by_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(worker.news, "run_news", lambda slugs: calls.append(slugs) or 0)
    sleeps: list[float] = []
    worker.news_feeds()
    worker.news_gdelt(sleep=sleeps.append)
    rss, *gdelt_calls = calls
    gdelt = [slug for call in gdelt_calls for slug in call]
    assert all(len(call) == 1 for call in gdelt_calls)  # one GDELT feed per call
    assert set(gdelt) == {f.slug for f in worker.feeds.active("gdelt")}
    assert sleeps == [worker.GDELT_FEED_SPACING_S] * (len(gdelt) - 1)
    assert rss
    assert not set(rss) & set(gdelt)


def test_sesnsp_reminder_once_per_month_when_stale(seeded: Session) -> None:
    sid = seeded.scalars(select(Source.id).where(Source.slug == "sesnsp")).one()
    seeded.add(CrimeIncidence(
        source_id=sid, retrieved_at=dt.datetime.now(dt.UTC), snapshot_date=dt.date(2026, 9, 30),
        methodology="2026", month=dt.date(2026, 9, 1), admin1_code="MX-SIN",
        admin2_code="25006", crime_type="Homicidio", crime_key="k", value=1,
    ))  # fmt: skip
    seeded.commit()
    assert worker.sesnsp_reminder(dt.date(2026, 10, 26)) is False  # 26 days old: fresh
    assert worker.sesnsp_reminder(dt.date(2026, 11, 26)) is True  # 57 days: stale
    assert worker.sesnsp_reminder(dt.date(2026, 11, 27)) is False  # already alerted
    alert = seeded.scalars(select(Alert).where(Alert.rule == "sesnsp_update_due")).one()
    assert "make ingest SOURCE=sesnsp" in alert.summary
