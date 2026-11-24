"""Run bookkeeping that survives an unreachable database (2026-11-23, run 6241)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import worker
from app.db.models import IngestRun
from app.ingest import runs


def _down() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("connection timeout expired"))


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    waited: list[float] = []
    monkeypatch.setattr(runs, "_sleep", waited.append)
    runs._UNFINISHED.clear()
    yield waited
    runs._UNFINISHED.clear()


def _flaky(monkeypatch: pytest.MonkeyPatch, failures: int) -> list[int]:
    """Make the first ``failures`` end-of-run writes fail as if the database were down."""
    real = runs._write_end
    calls: list[int] = []

    def write(run_id: int, values: dict[str, Any]) -> None:
        calls.append(run_id)
        if len(calls) <= failures:
            raise _down()
        real(run_id, values)

    monkeypatch.setattr(runs, "_write_end", write)
    return calls


def test_the_end_of_a_run_is_retried_while_the_database_is_down(
    session: Session, sleeps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    _flaky(monkeypatch, failures=2)
    with runs.ingest_run("test-job") as run:
        run.inserted = 3
    assert sleeps == list(runs.FINISH_RETRY_DELAYS[:2])
    row = session.get_one(IngestRun, run.id)
    assert (row.status, row.rows_inserted, row.pid) == ("ok", 3, os.getpid())


def test_an_end_that_cannot_be_written_is_kept_for_the_heartbeat(
    session: Session, sleeps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _flaky(monkeypatch, failures=len(runs.FINISH_RETRY_DELAYS) + 2)
    with runs.ingest_run("test-job") as run:  # a deferred run, as on 2026-11-23
        raise runs.DeferredRun("GDELT 429 after retries")
    assert len(calls) == len(runs.FINISH_RETRY_DELAYS) + 1  # no exception escaped
    assert session.get_one(IngestRun, run.id).status == "running"
    assert runs.flush_unfinished() == 0  # still down: kept for the next heartbeat
    worker.heartbeat()  # the database is back
    session.expire_all()
    row = session.get_one(IngestRun, run.id)
    assert (row.status, row.error) == ("deferred", "GDELT 429 after retries")
    assert runs._UNFINISHED == {}


def test_runs_left_running_by_ended_processes_are_closed(session: Session) -> None:
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    rows = {
        "legacy": IngestRun(job="news-x", status="running", pid=None),
        "ended": IngestRun(job="news-y", status="running", pid=ended.pid),
        "parent": IngestRun(job="news-z", status="running", pid=os.getppid()),
        "this": IngestRun(job="news-w", status="running", pid=os.getpid()),
        "done": IngestRun(job="news-v", status="ok", pid=ended.pid),
    }
    session.add_all(rows.values())
    session.commit()
    closed = runs.close_orphaned_runs()
    assert sorted(closed) == sorted([rows["legacy"].id, rows["ended"].id])
    session.expire_all()
    status = {k: session.get_one(IngestRun, r.id).status for k, r in rows.items()}
    assert status == {"legacy": "error", "ended": "error", "parent": "running",
                      "this": "running", "done": "ok"}  # fmt: skip
    legacy = session.get_one(IngestRun, rows["legacy"].id)
    assert (legacy.error, legacy.finished_at is not None) == (runs.INTERRUPTED, True)


def test_one_failing_gdelt_feed_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slugs = [f.slug for f in worker.feeds.active("gdelt")]
    ran: list[str] = []

    def run_news(batch: list[str]) -> int:
        ran.extend(batch)
        if batch == [slugs[0]]:
            raise _down()
        return 0

    monkeypatch.setattr(worker.news, "run_news", run_news)
    assert worker.news_gdelt(sleep=lambda _s: None) == 1
    assert ran == slugs
