"""Priority-topic panels (ADR 0009): escalation rungs, summaries and the topic filter.
All events are synthetic."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analytics.priority import uxs_rung
from app.db.models import Event, Source

NOW = dt.datetime(2026, 11, 20, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("platform", "payloads", "rung"),
    [
        ("suas_multirotor", ["camera_or_thermal"], 1),
        ("unknown", [], 1),
        ("fpv", ["none_reported"], 3),
        ("suas_multirotor", ["release_mechanism"], 4),
        ("suas_multirotor", ["explosive_or_grenade"], 4),
        ("fpv", ["ied"], 5),
        ("fpv", ["explosive_or_grenade", "release_mechanism"], 5),
    ],
)
def test_uxs_rung(platform: str, payloads: list[str], rung: int) -> None:
    assert uxs_rung(platform, payloads) == rung


@pytest.fixture
def topics(seeded: Session) -> dict[str, int]:
    src = Source(slug="synthetic-press", name="Synthetic Press", source_type="rss",
                 reliability="B")  # fmt: skip
    seeded.add(src)
    seeded.flush()

    def ev(key: str, day: dt.date, **kw: Any) -> int:
        e = Event(source_id=src.id, source_key=key, retrieved_at=NOW, event_date=day,
                  event_type=kw.pop("event_type", "Strategic developments"),
                  admin1_name=kw.pop("state", "Michoacán"), in_aoi=kw.pop("in_aoi", True),
                  prompt_version="extract-v9", **kw)  # fmt: skip
        seeded.add(e)
        seeded.flush()
        return e.id

    ids = {
        "attack": ev("a", dt.date(2026, 10, 3), event_type="Explosions/Remote violence",
                     uxs_activity="employment", uxs_platform="fpv",
                     uxs_missions=["attack"], uxs_payloads=["explosive_or_grenade"]),
        "watch": ev("b", dt.date(2026, 11, 2), uxs_activity="employment",
                    uxs_platform="suas_multirotor", uxs_missions=["surveillance"],
                    uxs_payloads=["camera_or_thermal"], state="Sinaloa"),
        "seized": ev("c", dt.date(2026, 11, 9), uxs_activity="recovery_or_seizure",
                     uxs_platform="suas_multirotor", uxs_payloads=["release_mechanism"]),
        "abroad": ev("d", dt.date(2026, 11, 9), uxs_activity="employment",
                     uxs_platform="fpv", in_aoi=False),
        "mining": ev("e", dt.date(2026, 11, 5), energy_method="illegal_line_connection",
                     energy_powered=["crypto_mining"], energy_facilitator="none_reported",
                     energy_scale="130 mining rigs", state="Sinaloa"),
        "plain": ev("f", dt.date(2026, 11, 6), event_type="Battles"),
    }  # fmt: skip
    seeded.commit()
    return ids


def test_uxs_summary_and_ladder(client: TestClient, topics: dict[str, int]) -> None:
    body = client.get("/priority/uxs").json()
    assert (body["total"], body["sources"]) == (3, 1)  # out-of-AOI event left out
    assert body["breakdown"]["activity"] == {"employment": 2, "recovery_or_seizure": 1}
    assert body["breakdown"]["platform"] == {"suas_multirotor": 2, "fpv": 1}
    assert [m["month"] for m in body["months"]] == ["2026-10", "2026-11"]
    assert body["states"] == {"Michoacán": 2, "Sinaloa": 1}
    ladder = {r["rung"]: r for r in body["ladder"]}
    assert (ladder[1]["use"], ladder[4]["capability"], ladder[5]["use"]) == (1, 1, 1)
    assert ladder[5]["first_seen"] == "2026-10-03"
    assert [r["rung"] for r in body["ladder"] if not r["captured"]] == [6, 7, 8]
    assert "owner framework" in body["ladder_note"]
    assert "not of underlying activity" in body["caveat"]
    windowed = client.get("/priority/uxs", params={"start": "2026-11-01"}).json()
    assert windowed["total"] == 2
    everywhere = client.get("/priority/uxs", params={"include_out_of_aoi": True}).json()
    assert everywhere["total"] == 4


def test_energy_summary(client: TestClient, topics: dict[str, int]) -> None:
    body = client.get("/priority/energy-theft").json()
    assert body["total"] == 1
    assert body["breakdown"]["powered"] == {"crypto_mining": 1}
    assert body["breakdown"]["method"] == {"illegal_line_connection": 1}
    assert body["states"] == {"Sinaloa": 1}


def test_events_topic_filter_and_fields(client: TestClient, topics: dict[str, int]) -> None:
    uxs = client.get("/events", params={"topic": "uxs"}).json()["items"]
    assert {e["id"] for e in uxs} == {topics["attack"], topics["watch"], topics["seized"]}
    both = client.get("/events", params={"topic": ["uxs", "energy_theft"]}).json()["items"]
    assert len(both) == 4
    mining = next(e for e in both if e["id"] == topics["mining"])
    assert (mining["energy_powered"], mining["energy_scale"]) == (
        ["crypto_mining"],
        "130 mining rigs",
    )
    attack = client.get(f"/events/{topics['attack']}").json()
    assert (attack["uxs_platform"], attack["uxs_payloads"]) == ("fpv", ["explosive_or_grenade"])
