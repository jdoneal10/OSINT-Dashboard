from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Actor, Event, IngestRun, ReferenceArea, actor_events
from app.ingest import acled
from tests.acled_fake import FakeAcled, _json, fake_credentials


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_credentials(monkeypatch)
    # These tests were written for the Phase 1 AOI (six border states); see the phase-2 tests.
    monkeypatch.setattr(get_settings(), "acled_aoi_phase", 1)


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


def test_phase2_aoi_covers_all_of_mexico(seeded: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "acled_aoi_phase", 2)
    _backfill(seeded)
    events = _events(seeded)
    assert "MEX900003" in events  # Sinaloa: outside Phase 1, inside Phase 2
    assert events["MEX900003"].admin1_code == "MX-SIN"


def test_reprocess_applies_new_aoi_and_keeps_deletions(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _backfill(seeded)  # phase 1: Sinaloa event filtered out, raw pages written to disk
    with FakeAcled().client() as http:
        acled.run_deleted(http=http)  # MEX900002 deleted upstream
    assert "MEX900003" not in _events(seeded)

    monkeypatch.setattr(get_settings(), "acled_aoi_phase", 2)
    acled.run_reprocess()
    events = _events(seeded)
    assert "MEX900003" in events  # newly in scope, from raw pages only
    assert "MEX900002" not in events  # replayed deletion keeps it gone
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == acled.JOB_REPROCESS)).one()
    assert run.status == "ok"
    assert run.rows_deleted == 1


def test_admin2_assigned_by_point_in_polygon(seeded: Session) -> None:
    # Synthetic municipality square around the synthetic Ensenada-area event (31.86, -116.60).
    seeded.add(
        ReferenceArea(
            slug="mx-mun-test",
            name="Synthetic Municipality",
            area_type="admin2",
            country_iso3="MEX",
            admin1_code="MX-BCN",
            admin2_code="02999",
            phase=2,
            geom=func.ST_GeogFromText(
                "SRID=4326;MULTIPOLYGON(((-117 31.5,-116.2 31.5,-116.2 32.2,-117 32.2,-117 31.5)))"
            ),
            sources=[],
        )
    )
    seeded.commit()
    _backfill(seeded)
    events = _events(seeded)
    assert events["MEX900001"].admin2_code == "02999"
    assert events["MEX900006"].admin2_code is None  # Tamaulipas: outside the square


def test_large_page_is_chunked_under_parameter_limit(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full 5,000-row page in scope must not exceed Postgres's 65,535 bind parameters."""
    monkeypatch.setattr(get_settings(), "acled_aoi_phase", 2)
    template = _json("events-page2")["data"][0]
    rows = [
        {**template, "event_id_cnty": f"MEXBIG{i:05d}", "timestamp": str(1700001000 + i)}
        for i in range(5000)
    ]
    fake = FakeAcled(events={"status": 200, "success": True, "data": rows, "next_cursor": None})
    with fake.client() as http:
        acled.run_events(dt.date(2024, 1, 1), http=http)
    assert seeded.scalar(select(func.count()).select_from(Event)) == 5000
