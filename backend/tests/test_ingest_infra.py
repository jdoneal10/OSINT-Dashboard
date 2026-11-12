from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IngestRun
from app.ingest.http import USER_AGENT, PoliteClient, RobotsDisallowedError
from app.ingest.raw import write_raw
from app.ingest.runs import file_already_ingested, ingest_run, last_successful_params

# Excerpt of cbp.gov/robots.txt (2026-11-11), including its double-space formatting.
CBP_ROBOTS = """User-agent: *
Disallow: /core/
Disallow: /search/
#Disallow the files/assets/documents directory 10/04/24
Disallow:  /sites/default/files/assets/documents/
Disallow:  /sites/default/files/assets/documents/*
User-agent: PetalBot
Disallow: /
"""


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _client(handler, clock: FakeClock | None = None, **kw) -> PoliteClient:  # type: ignore[no-untyped-def]
    clock = clock or FakeClock()
    return PoliteClient(
        transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.clock, **kw
    )


def test_robots_disallowed_path_is_refused() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=CBP_ROBOTS)
        return httpx.Response(200, text="ok")

    with _client(handler) as c:
        ok = c.get("https://www.cbp.gov/sites/default/files/2026-10/nationwide-drugs.csv")
        assert ok.status_code == 200
        with pytest.raises(RobotsDisallowedError):
            c.get("https://www.cbp.gov/sites/default/files/assets/documents/2023-Oct/x.csv")
    assert "/sites/default/files/assets/documents/2023-Oct/x.csv" not in seen
    assert seen.count("/robots.txt") == 1  # cached per origin


def test_api_requests_skip_robots_but_send_generic_user_agent() -> None:
    agents: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path != "/robots.txt"
        agents.append(req.headers["user-agent"])
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as c:
        c.get("https://api.example.org/read", crawl=False)
    assert agents == [USER_AGENT]
    assert "@" not in USER_AGENT


def test_retries_on_429_honoring_retry_after() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200)

    clock = FakeClock()
    with _client(handler, clock, min_interval=0) as c:
        assert c.get("https://api.example.org/x", crawl=False).status_code == 200
    assert calls["n"] == 3
    assert clock.slept.count(7.0) == 2


def test_gives_up_after_max_retries() -> None:
    clock = FakeClock()
    with _client(lambda _r: httpx.Response(503), clock, min_interval=0, max_retries=2) as c:
        assert c.get("https://api.example.org/x", crawl=False).status_code == 503


def test_throttles_requests_per_host() -> None:
    clock = FakeClock()
    with _client(lambda _r: httpx.Response(200), clock, min_interval=1.0) as c:
        for _ in range(3):
            c.get("https://api.example.org/x", crawl=False)
    assert clock.slept == [1.0, 1.0]


def test_write_raw(raw_dir: Path) -> None:
    snap = write_raw("cbp", 7, "nationwide drugs.csv", b"a,b\n1,2\n")
    assert snap.path.read_bytes() == b"a,b\n1,2\n"
    assert snap.path.parent.parent.name == "cbp"
    assert snap.path.name == "7-nationwide_drugs.csv"
    assert len(snap.sha256) == 64
    assert snap.path.is_relative_to(raw_dir)


def test_ingest_run_records_success_and_watermark(session: Session) -> None:
    with ingest_run("test-job", params={"since": "2020-01-01"}) as run:
        run.inserted = 5
        run.params["watermark"] = 123
        run.params["files"] = [{"sha256": "abc"}]
    row = session.scalars(select(IngestRun).where(IngestRun.id == run.id)).one()
    assert (row.status, row.rows_inserted) == ("ok", 5)
    assert row.finished_at is not None
    assert last_successful_params("test-job") == {
        "since": "2020-01-01",
        "watermark": 123,
        "files": [{"sha256": "abc"}],
    }
    assert file_already_ingested("test-job", "abc")
    assert not file_already_ingested("test-job", "zzz")


def test_ingest_run_records_failure_with_redacted_error(session: Session) -> None:
    with pytest.raises(RuntimeError), ingest_run("test-job") as run:
        raise RuntimeError("boom password=hunter2hunter2")
    row = session.get_one(IngestRun, run.id)
    assert row.status == "error"
    assert row.error is not None
    assert "hunter2" not in row.error
    assert last_successful_params("test-job") is None
