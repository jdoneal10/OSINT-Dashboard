from __future__ import annotations

import logging

import pytest

from app import worker
from app.core.config import get_settings


def test_scheduler_registers_source_jobs() -> None:
    scheduler = worker.build_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"heartbeat", "acled-events", "acled-deleted", "cbp"}
    assert "hour='11'" in str(jobs["acled-events"].trigger)
    assert "day_of_week='sun'" in str(jobs["acled-deleted"].trigger)


def test_scheduled_ingest_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "scheduled_ingest", False)
    assert [j.id for j in worker.build_scheduler().get_jobs()] == ["heartbeat"]


def test_failing_job_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> None:
        raise RuntimeError("upstream down")

    with caplog.at_level(logging.ERROR):
        worker._guarded("test-job", boom)()
    assert "scheduled job test-job failed" in caplog.text
