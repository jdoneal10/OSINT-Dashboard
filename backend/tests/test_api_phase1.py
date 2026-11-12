from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Actor
from app.ingest import acled, cbp
from tests.acled_fake import FakeAcled, fake_credentials

CBP_FIX = Path(__file__).parent / "fixtures" / "cbp"


@pytest.fixture
def loaded(seeded: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Reference data + synthetic ACLED events + CBP fixtures (drugs in two snapshots)."""
    fake_credentials(monkeypatch)
    monkeypatch.setattr(get_settings(), "acled_aoi_phase", 1)  # tests written for Phase 1
    with FakeAcled().client() as http:
        acled.run_events(dt.date(2018, 1, 1), until=dt.date(2026, 11, 1), http=http)
    cbp.run_local(CBP_FIX / "encounters-aor.csv", snapshot=dt.date(2026, 10, 15))
    cbp.run_local(CBP_FIX / "nationwide-drugs.csv", snapshot=dt.date(2026, 9, 4))
    revised = tmp_path / "nationwide-drugs.csv"
    revised.write_bytes(
        (CBP_FIX / "nationwide-drugs.csv").read_bytes().replace(b"14,120.5", b"15,130.5")
    )
    cbp.run_local(revised, snapshot=dt.date(2026, 10, 15))
    return seeded


def _actor_id(session: Session, slug: str) -> int:
    return session.scalars(select(Actor.id).where(Actor.slug == slug)).one()


# --------------------------------------------------------------------------- events


@pytest.mark.usefixtures("loaded")
def test_events_paginate_newest_first_with_provenance(client: TestClient) -> None:
    first = client.get("/events", params={"limit": 3}).json()
    assert len(first["items"]) == 3
    assert first["next_cursor"]
    second = client.get("/events", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    assert second["next_cursor"] is None
    keys = [e["source_key"] for e in first["items"] + second["items"]]
    assert sorted(keys) == ["MEX900001", "MEX900002", "MEX900004", "MEX900006"]
    dates = [e["event_date"] for e in first["items"] + second["items"]]
    assert dates == sorted(dates, reverse=True)
    item = first["items"][0]
    assert item["source"] == "acled"
    assert item["retrieved_at"]
    assert item["actors"]
    assert {"id", "name", "type", "role"} <= set(item["actors"][0])


def test_events_filters(client: TestClient, loaded: Session) -> None:
    def keys(**params: Any) -> set[str]:
        return {e["source_key"] for e in client.get("/events", params=params).json()["items"]}

    assert keys(admin1="MX-COA") == {"MEX900002"}
    assert keys(event_type="Battles") == {"MEX900006"}
    assert keys(start="2024-03-14") >= {"MEX900004", "MEX900006"}
    # Filtering on the parent cartel includes its faction's events.
    assert keys(actor=_actor_id(loaded, "cartel-de-sinaloa")) == {"MEX900001", "MEX900004"}
    assert keys(bbox="-117.5,31,-116,32.5") == {"MEX900001"}
    assert client.get("/events", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get("/events", params={"cursor": "garbage"}).status_code == 422


@pytest.mark.usefixtures("loaded")
def test_events_geojson_timeseries_types_and_detail(client: TestClient) -> None:
    fc = client.get("/events/geojson").json()
    assert fc["type"] == "FeatureCollection"
    assert fc["truncated"] is False
    assert len(fc["features"]) == 4
    props = fc["features"][0]["properties"]
    assert set(props) == {"id", "d", "t", "f", "gp", "a"}

    ts = client.get("/events/timeseries", params={"admin1": ["MX-TAM"]}).json()
    assert ts == [{"month": "2024-03-01", "admin1_code": "MX-TAM", "events": 1, "fatalities": 4}]

    types = {t["event_type"]: t["events"] for t in client.get("/events/types").json()}
    assert types["Battles"] == 1

    detail = client.get(f"/events/{props['id']}").json()
    assert detail["id"] == props["id"]
    assert client.get("/events/999999").status_code == 404


# --------------------------------------------------------------------------- border


@pytest.mark.usefixtures("loaded")
def test_border_metrics_grouped(client: TestClient) -> None:
    body = client.get(
        "/border/metrics",
        params={"metric": "encounters", "aor": "usbp-san-diego", "group_by": "demographic"},
    ).json()
    assert body["series"] == [{"month": "2023-10-01", "group": "Single Adults", "value": 1230.0}]
    assert body["unit"] == "persons"
    assert "not endorsed by CBP" in body["notice"]
    assert (
        client.get(
            "/border/metrics", params={"metric": "encounters", "aor": "usbp-nowhere"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/border/metrics",
            params={"metric": "encounters", "aor": "usbp-san-diego", "group_by": "evil"},
        ).status_code
        == 422
    )


@pytest.mark.usefixtures("loaded")
def test_border_metrics_latest_snapshot_and_as_of(client: TestClient) -> None:
    params = {"metric": "seizure_lbs", "aor": "ofo-el-paso"}
    latest = client.get("/border/metrics", params=params).json()
    assert latest["series"][0]["value"] == 130.5
    assert latest["snapshots"] == ["2026-10-15"]
    before = client.get("/border/metrics", params={**params, "as_of": "2026-09-30"}).json()
    assert before["series"][0]["value"] == 120.5


@pytest.mark.usefixtures("loaded")
def test_seizures_by_drug_type(client: TestClient) -> None:
    body = client.get("/seizures", params={"aor": ["usbp-tucson", "ofo-el-paso"]}).json()
    weight = {(p["group"], p["month"]): p["value"] for p in body["weight"]["series"]}
    assert weight[("Methamphetamine", "2025-03-01")] == 1034.25
    assert weight[("Fentanyl", "2024-11-01")] == 130.5
    events = {p["group"]: p["value"] for p in body["events"]["series"]}
    assert events["Methamphetamine"] == 9
    only = client.get("/seizures", params={"aor": "usbp-tucson", "drug_type": "Cocaine"}).json()
    assert only["weight"]["series"] == []


# --------------------------------------------------------------------------- actors & reference


@pytest.mark.usefixtures("loaded")
def test_actors_search_and_counts(client: TestClient) -> None:
    gulf = client.get("/actors", params={"q": "gulf"}).json()
    assert gulf[0]["slug"] == "cartel-del-golfo"
    assert gulf[0]["event_count"] == 1
    assert "Gulf Cartel" in gulf[0]["aliases"]
    accented = client.get("/actors", params={"q": "Cártel del Golfo"}).json()
    assert accented[0]["slug"] == "cartel-del-golfo"
    with_events = client.get("/actors", params={"with_events": True}).json()
    assert all(a["event_count"] > 0 for a in with_events)
    states = client.get("/actors", params={"type": "state"}).json()
    assert states
    assert all(a["actor_type"] == "state" for a in states)


@pytest.mark.usefixtures("seeded")
def test_reference_adjacency(client: TestClient) -> None:
    body = client.get("/reference/adjacency").json()
    assert len(body) == 9
    tucson = next(x for x in body if x["sector"] == "usbp-tucson")
    assert tucson["adjacent_admin1"] == ["MX-SON"]
    assert tucson["field_office"] == "ofo-tucson"
    assert tucson["method"].startswith("Analyst-derived")


def test_events_meta(client: TestClient, loaded: Session) -> None:
    meta = client.get("/events/meta").json()
    assert meta["total"] == 4
    assert meta["sources"] == ["acled"]
    assert meta["min_date"] <= meta["max_date"]
    accessed = dt.datetime.fromisoformat(meta["accessed"])
    assert abs((dt.datetime.now(dt.UTC) - accessed).total_seconds()) < 300
