from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Actor, Event, IngestRun, actor_events
from app.ingest import acled
from app.ingest.http import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "acled"
TOKEN = "synthetic-test-token"  # not a real credential


def _json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIX / f"{name}.json").read_text())
    return data


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = {"ACLED_USERNAME": "user@example.org", "ACLED_PASSWORD": "not-a-real-password"}
    monkeypatch.setattr(acled, "require_secret", lambda name: SecretStr(secrets[name]))


class FakeAcled:
    """Minimal fake of ACLED's token, read and deleted endpoints."""

    def __init__(self, events: dict[str, Any] | None = None, expire_once: bool = False) -> None:
        self.events = events  # if set, every read returns this page
        self.expire_once = expire_once
        self.calls: list[httpx.Request] = []
        self.token_requests = 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        path = req.url.path
        if path == "/robots.txt":
            raise AssertionError("API calls must not consult robots.txt")
        if path == "/oauth/token":
            self.token_requests += 1
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert form["grant_type"] == "password"
            assert form["client_id"] == "acled"
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 86400})
        if req.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        if self.expire_once:
            self.expire_once = False
            return httpx.Response(401)
        if path == "/api/acled/read":
            if self.events is not None:
                return httpx.Response(200, json=self.events)
            page = "events-page2" if req.url.params.get("cursor") == "c2" else "events-page1"
            return httpx.Response(200, json=_json(page))
        if path == "/api/deleted/read":
            return httpx.Response(200, json=_json("deleted"))
        return httpx.Response(404)

    def client(self) -> PoliteClient:
        return PoliteClient(
            transport=httpx.MockTransport(self.handler), min_interval=0, sleep=lambda _s: None
        )


def _events(session: Session) -> dict[str, Event]:
    session.expire_all()
    return {e.source_key: e for e in session.scalars(select(Event))}


def _backfill(session: Session, fake: FakeAcled | None = None) -> FakeAcled:
    fake = fake or FakeAcled()
    with fake.client() as http:
        acled.run_events(dt.date(2018, 1, 1), until=dt.date(2026, 11, 1), http=http)
    return fake


def test_backfill_pages_filters_aoi_and_skips_invalid(seeded: Session) -> None:
    fake = _backfill(seeded)
    events = _events(seeded)
    assert set(events) == {"MEX900001", "MEX900002", "MEX900004", "MEX900006"}
    assert events["MEX900001"].admin1_code == "MX-BCN"
    assert events["MEX900002"].admin1_code == "MX-COA"  # long official name
    assert events["MEX900004"].admin1_code == "MX-SON"  # blank admin1 → point-in-polygon
    assert events["MEX900006"].fatalities == 4
    assert events["MEX900001"].attributes["actor1"] == "Sinaloa Cartel"
    assert events["MEX900001"].confidence is not None

    reads = [c for c in fake.calls if c.url.path == "/api/acled/read"]
    assert [c.url.params.get("cursor") for c in reads] == ["0", "c2"]
    assert reads[0].url.params["country"] == "Mexico"
    assert reads[0].url.params["event_date"] == "2018-01-01|2026-11-01"
    assert fake.token_requests == 1

    run = seeded.scalars(select(IngestRun).where(IngestRun.job == acled.JOB_EVENTS)).one()
    assert (run.status, run.rows_inserted) == ("ok", 4)
    assert run.params["outside"] == 1
    assert run.params["invalid"] == 1
    assert run.params["max_timestamp"] == 1700000006


def test_backfill_rerun_is_idempotent(seeded: Session) -> None:
    _backfill(seeded)
    links = seeded.scalar(select(func.count()).select_from(actor_events))
    _backfill(seeded)
    assert len(_events(seeded)) == 4
    assert seeded.scalar(select(func.count()).select_from(actor_events)) == links
    runs = seeded.scalars(
        select(IngestRun).where(IngestRun.job == acled.JOB_EVENTS).order_by(IngestRun.id)
    ).all()
    assert (runs[-1].rows_inserted, runs[-1].rows_updated) == (0, 4)


def test_incremental_uses_watermark_updates_and_removes_moved_events(seeded: Session) -> None:
    _backfill(seeded)
    fake = FakeAcled(events=_json("events-incremental"))
    with fake.client() as http:
        acled.run_events(http=http)
    read = next(c for c in fake.calls if c.url.path == "/api/acled/read")
    assert read.url.params["timestamp"] == "1700000006"
    assert read.url.params["timestamp_where"] == ">="

    events = _events(seeded)
    assert events["MEX900001"].fatalities == 3  # revised in place
    assert "MEX900006" not in events  # revised out of the AOI → removed


def test_incremental_without_backfill_refuses(seeded: Session) -> None:
    with FakeAcled().client() as http, pytest.raises(RuntimeError, match="backfill first"):
        acled.run_events(http=http)


def test_deleted_reconciliation(seeded: Session) -> None:
    _backfill(seeded)
    fake = FakeAcled()
    with fake.client() as http:
        acled.run_deleted(http=http)
    assert "MEX900002" not in _events(seeded)
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == acled.JOB_DELETED)).one()
    assert run.rows_deleted == 1
    # The watermark never moves backwards from our first backfill's start time.
    first = seeded.scalars(select(IngestRun).where(IngestRun.job == acled.JOB_EVENTS)).one()
    assert run.params["max_deleted_timestamp"] == first.params["started_unix"]
    call = next(c for c in fake.calls if c.url.path == "/api/deleted/read")
    assert call.url.params["deleted_timestamp_where"] == ">="


def test_reauthenticates_once_on_expired_token(seeded: Session) -> None:
    fake = _backfill(seeded, FakeAcled(expire_once=True))
    assert fake.token_requests == 2
    assert len(_events(seeded)) == 4


def test_api_error_payload_fails_run(seeded: Session) -> None:
    fake = FakeAcled(events={"status": 403, "success": False, "messages": ["access denied"]})
    with fake.client() as http, pytest.raises(acled.AcledApiError, match="access denied"):
        acled.run_events(dt.date(2024, 1, 1), http=http)
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == acled.JOB_EVENTS)).one()
    assert run.status == "error"


def test_actor_links_follow_acled_dyad(seeded: Session) -> None:
    _backfill(seeded)
    rows = seeded.execute(
        select(Event.source_key, Actor.slug, Actor.actor_type, actor_events.c.role)
        .join(actor_events, actor_events.c.event_id == Event.id)
        .join(Actor, Actor.id == actor_events.c.actor_id)
    ).all()
    by_event: dict[str, set[tuple[str, str]]] = {}
    for key, slug, _type, role in rows:
        by_event.setdefault(key, set()).add((slug, role))
    assert ("cartel-de-sinaloa", "actor1") in by_event["MEX900001"]
    assert ("cjng", "actor1") in by_event["MEX900002"]  # "CJNG: Jalisco New Generation Cartel"
    assert ("cartel-del-golfo", "actor1") in by_event["MEX900006"]  # alias "Gulf Cartel"
    roles2 = {r for _s, r in by_event["MEX900002"]}
    assert roles2 == {"actor1", "actor2", "assoc_actor2"}
    assert len([1 for _s, r in by_event["MEX900002"] if r == "assoc_actor2"]) == 2

    types = {slug: t for _k, slug, t, _r in rows}
    police = next(s for s in types if s.startswith("police-forces-of-mexico"))
    assert types[police] == "state"
    faction = seeded.scalars(select(Actor).where(Actor.canonical_name == "Synthetic Faction")).one()
    parent = seeded.scalars(select(Actor).where(Actor.slug == "cartel-de-sinaloa")).one()
    assert (faction.actor_type, faction.parent_id) == ("faction", parent.id)
