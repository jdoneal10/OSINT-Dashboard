from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CrimeIncidence,
    Designation,
    Document,
    Event,
    LLMUsage,
    Seizure,
    Source,
    event_documents,
    seizure_documents,
)
from app.enrich import admiralty, dedupe

NOW = dt.datetime(2026, 11, 10, 12, tzinfo=dt.UTC)


def _doc(session: Session, sid: int, key: str, status: str = "extracted", **kw: object) -> int:
    doc = Document(
        source_id=sid,
        source_key=key,
        retrieved_at=NOW,
        published_at=NOW - dt.timedelta(hours=len(key)),
        title=f"Title {key}",
        original_text=f"Texto original {key}",
        translated_text=f"Summary {key}",
        pipeline_status=status,
        relevance_score=Decimal("0.9" if status == "extracted" else "0.1"),
        prompt_version="extract-v1",
        **kw,
    )
    session.add(doc)
    session.flush()
    return doc.id


def _event(
    session: Session, sid: int, doc_id: int, key: str, *, in_aoi: bool = True,
    lon: float = -107.39, lat: float = 24.80,
) -> int:  # fmt: skip
    ev = Event(
        source_id=sid, source_key=key, retrieved_at=NOW, event_date=dt.date(2026, 11, 9),
        event_type="Battles", fatalities=3, admin1_code="MX-SIN" if in_aoi else None,
        geom=func.ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})") if in_aoi else None,
        in_aoi=in_aoi, prompt_version="extract-v1",
    )  # fmt: skip
    session.add(ev)
    session.flush()
    session.execute(event_documents.insert().values(event_id=ev.id, document_id=doc_id))
    return ev.id


@pytest.fixture
def news(seeded: Session) -> dict[str, int]:
    s = seeded
    a = Source(slug="news-a", name="News A", source_type="rss", reliability="B")
    b = Source(slug="news-b", name="News B", source_type="rss", reliability="A")
    s.add_all([a, b])
    s.flush()
    ids: dict[str, int] = {"src_a": a.id}
    ids["doc_in"] = _doc(s, a.id, "in")
    ids["ev_in"] = _event(s, a.id, ids["doc_in"], "in:e0")
    ids["doc_corr"] = _doc(s, b.id, "corr")
    ids["ev_corr"] = _event(s, b.id, ids["doc_corr"], "corr:e0", lon=-107.38)
    ids["doc_out"] = _doc(s, a.id, "outside")
    ids["ev_out"] = _event(s, a.id, ids["doc_out"], "out:e0", in_aoi=False)
    ids["doc_filtered"] = _doc(s, a.id, "filtered", status="filtered_out")
    ids["doc_dup"] = _doc(s, b.id, "dup", duplicate_of_id=ids["doc_in"])
    sz = Seizure(
        source_id=a.id, source_key="in:s0", retrieved_at=NOW, seizure_date=dt.date(2026, 11, 9),
        substance="fentanyl", quantity=Decimal("12"), unit="kg", prompt_version="extract-v1",
    )  # fmt: skip
    s.add(sz)
    s.flush()
    s.execute(seizure_documents.insert().values(seizure_id=sz.id, document_id=ids["doc_in"]))
    ids["sz_in"] = sz.id
    dedupe.cluster_events(s)
    admiralty.score_clusters(s)
    s.commit()
    return ids


# --------------------------------------------------------------------------- documents


def test_feed_hides_out_of_aoi_filtered_and_duplicates(
    client: TestClient, news: dict[str, int]
) -> None:
    items = client.get("/documents").json()["items"]
    assert [i["id"] for i in items] == [news["doc_in"], news["doc_corr"]]  # newest first
    top = items[0]
    assert (top["n_events"], top["n_seizures"], top["in_aoi"]) == (1, 1, True)
    assert top["source"] == {"slug": "news-a", "name": "News A", "reliability": "B"}
    # Two independent sources corroborate one cluster: best reliability A, credibility 2.
    assert top["clusters"][0]["n_independent_sources"] == 2
    assert top["admiralty"] == "A2"

    wide = client.get("/documents", params={"include_out_of_aoi": True}).json()["items"]
    assert {i["id"] for i in wide} == {news["doc_in"], news["doc_corr"], news["doc_out"]}
    assert next(i for i in wide if i["id"] == news["doc_out"])["in_aoi"] is False

    filtered = client.get("/documents", params={"status": "filtered_out"}).json()["items"]
    assert [i["id"] for i in filtered] == [news["doc_filtered"]]


def test_feed_filters_and_pagination(client: TestClient, news: dict[str, int]) -> None:
    first = client.get("/documents", params={"limit": 1}).json()
    second = client.get("/documents", params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert [first["items"][0]["id"], second["items"][0]["id"]] == [news["doc_in"], news["doc_corr"]]
    assert second["next_cursor"] is None
    by_source = client.get("/documents", params={"source": "news-b"}).json()["items"]
    assert [i["id"] for i in by_source] == [news["doc_corr"]]
    assert client.get("/documents", params={"admin1": "MX-SON"}).json()["items"] == []
    assert len(client.get("/documents", params={"q": "summary in"}).json()["items"]) == 1
    assert client.get("/documents", params={"cursor": "junk"}).status_code == 422


def test_document_sources(client: TestClient, news: dict[str, int]) -> None:
    rows = client.get("/documents/sources").json()
    assert [(r["slug"], r["documents"]) for r in rows] == [("news-a", 2), ("news-b", 2)]


def test_document_detail(client: TestClient, news: dict[str, int]) -> None:
    d = client.get(f"/documents/{news['doc_in']}").json()
    assert d["original_text"] == "Texto original in"
    assert d["summary_en"] == "Summary in"
    assert [e["id"] for e in d["events"]] == [news["ev_in"]]
    assert d["events"][0]["document_ids"] == [news["doc_in"]]
    assert d["events"][0]["evidence"] is None
    assert [s["substance"] for s in d["seizures"]] == ["fentanyl"]
    assert d["duplicates"] == [news["doc_dup"]]
    assert (d["quarantine"], d["labels"]) == ([], [])
    assert client.get("/documents/999999").status_code == 404


def test_cluster_detail(client: TestClient, news: dict[str, int], seeded: Session) -> None:
    cid = seeded.get_one(Event, news["ev_in"]).cluster_id
    c = client.get(f"/clusters/{cid}").json()
    assert {e["id"] for e in c["events"]} == {news["ev_in"], news["ev_corr"]}
    assert {d["id"] for d in c["documents"]} == {news["doc_in"], news["doc_corr"]}
    assert (c["admiralty"], c["n_independent_sources"], c["assessments"]) == ("A2", 2, [])
    assert c["lon"] is not None
    assert client.get("/clusters/999999").status_code == 404


def test_acled_corroboration_is_flagged(
    client: TestClient, news: dict[str, int], seeded: Session
) -> None:
    cid = seeded.get_one(Event, news["ev_in"]).cluster_id
    acled = seeded.scalars(select(Source.id).where(Source.slug == "acled")).one()
    seeded.add(Event(source_id=acled, source_key="MEX-9", retrieved_at=NOW, cluster_id=cid,
                     event_date=dt.date(2026, 11, 9), event_type="Battles"))  # fmt: skip
    seeded.commit()
    top = client.get("/documents").json()["items"][0]
    assert top["clusters"][0]["acled_corroborated"] is True
    c = client.get(f"/clusters/{cid}").json()
    assert c["acled_corroborated"] is True
    assert "acled" in {e["source"] for e in c["events"]}


# --------------------------------------------------------------------------- events


def test_events_source_and_aoi_filters(client: TestClient, news: dict[str, int]) -> None:
    items = client.get("/events", params={"source": ["news-a", "news-b"]}).json()["items"]
    assert {e["id"] for e in items} == {news["ev_in"], news["ev_corr"]}
    assert all(e["in_aoi"] and e["cluster_id"] for e in items)
    wide = client.get("/events", params={"source": "news-a", "include_out_of_aoi": True}).json()[
        "items"
    ]
    assert {e["id"] for e in wide} == {news["ev_in"], news["ev_out"]}
    assert client.get("/events", params={"source": "acled"}).json()["items"] == []


# --------------------------------------------------------------------------- designations


def test_designations_hide_individual_listings(client: TestClient, seeded: Session) -> None:
    ofac = seeded.scalars(select(Source.id).where(Source.slug == "ofac")).one()
    for key, party, program in (
        ("1", {"name": "EXAMPLE TRADING S.A.", "type": "entity"}, "SDGT;SDNTK"),
        ("2", {"name": "SYNTHETIC PERSON", "type": "individual"}, "SDNTK"),
    ):
        seeded.add(Designation(
            source_id=ofac, source_key=key, retrieved_at=NOW, designation_type="sdn",
            program=program, action="listed", action_date=dt.date(2026, 1, int(key)),
            title="SDN listing", listed_parties=[party],
        ))  # fmt: skip
    seeded.commit()
    page = client.get("/designations").json()
    assert page["total"] == 1
    assert page["items"][0]["listed_parties"][0]["type"] == "entity"
    both = client.get("/designations", params={"include_individual_listings": True}).json()
    assert both["total"] == 2
    tok = client.get("/designations", params={"program": "sdntk"}).json()
    assert tok["total"] == 1  # token match on "SDGT;SDNTK"
    assert client.get("/designations", params={"program": "SDN"}).json()["total"] == 0


# --------------------------------------------------------------------------- crime incidence


def test_crime_incidence_latest_snapshot_and_methodology_guard(
    client: TestClient, seeded: Session
) -> None:
    sesnsp = seeded.scalars(select(Source.id).where(Source.slug == "sesnsp")).one()

    def row(method: str, month: dt.date, a2: str, value: int, snap: dt.date) -> CrimeIncidence:
        return CrimeIncidence(
            source_id=sesnsp, retrieved_at=NOW, snapshot_date=snap, methodology=method,
            month=month, admin1_code="MX-SIN", admin2_code=a2, crime_type="Homicidio",
            crime_key=f"Homicidio|{a2}", value=value,
        )  # fmt: skip

    old, new = dt.date(2026, 1, 20), dt.date(2026, 2, 20)
    seeded.add_all([
        row("2015-2025", dt.date(2025, 11, 1), "25006", 99, old),  # superseded snapshot
        row("2015-2025", dt.date(2025, 11, 1), "25006", 10, new),
        row("2015-2025", dt.date(2025, 12, 1), "25006", 5, new),
        row("2015-2025", dt.date(2025, 12, 1), "25012", 7, new),
        row("2026", dt.date(2026, 1, 1), "25006", 4, new),
    ])  # fmt: skip
    seeded.commit()
    r = client.get(
        "/crime-incidence",
        params={"crime_type": "Homicidio", "start": "2025-11-15", "end": "2025-12-01"},
    ).json()
    assert (r["methodology"], r["start"], r["end"]) == ("2015-2025", "2025-11-01", "2025-12-01")
    assert [(i["admin2_code"], i["value"]) for i in r["items"]] == [("25006", 15), ("25012", 7)]
    spans = client.get(
        "/crime-incidence",
        params={"crime_type": "Homicidio", "start": "2025-12-01", "end": "2026-01-01"},
    )
    assert spans.status_code == 422
    assert "not comparable" in spans.json()["detail"]
    meta = client.get("/crime-incidence/meta").json()
    assert [m["methodology"] for m in meta] == ["2015-2025", "2026"]
    assert meta[0]["snapshot_date"] == "2026-02-20"


# --------------------------------------------------------------------------- LLM usage


def test_llm_usage(client: TestClient, seeded: Session) -> None:
    haiku = {"stage": "extract", "model": "claude-haiku-5-5", "prompt_version": "v"}
    seeded.add_all(
        [
            LLMUsage(**haiku, cost_usd=Decimal("1.5")),
            LLMUsage(**haiku, cost_usd=Decimal("0.5"), status="invalid"),
        ]
    )
    seeded.commit()
    u = client.get("/llm/usage").json()
    assert (u["spent_usd"], u["cap_usd"], u["pause_threshold_usd"], u["paused"]) == (
        2.0,
        75.0,
        60.0,
        False,
    )
    assert (u["calls"], u["failed_calls"]) == (2, 1)
    assert u["by_stage"] == [
        {"stage": "extract", "model": "claude-haiku-5-5", "calls": 2, "cost_usd": 2.0}
    ]


# --------------------------------------------------------------------------- labels


def test_label_upsert_validation_and_delete(client: TestClient, news: dict[str, int]) -> None:
    body = {"document_id": news["doc_in"], "target_table": "events", "target_id": news["ev_in"],
            "verdict": "partial", "field": "fatalities", "note": "article says 4"}  # fmt: skip
    first = client.put("/labels", json=body).json()
    assert (first["verdict"], first["prompt_version"]) == ("partial", "extract-v1")
    again = client.put("/labels", json=body | {"verdict": "incorrect"}).json()
    assert (again["id"], again["verdict"]) == (first["id"], "incorrect")
    # A record from another document is rejected.
    wrong = client.put("/labels", json=body | {"target_id": news["ev_corr"]})
    assert wrong.status_code == 422
    assert client.put("/labels", json=body | {"verdict": "maybe"}).status_code == 422
    assert len(client.get("/labels", params={"document_id": news["doc_in"]}).json()) == 1
    assert client.delete(f"/labels/{first['id']}").status_code == 204
    assert client.delete(f"/labels/{first['id']}").status_code == 404


def test_label_queue_is_stratified_and_tracks_progress(
    client: TestClient, news: dict[str, int]
) -> None:
    q = client.get("/labels/queue", params={"size": 10, "filtered_share": 0.5}).json()
    ids = [i["document_id"] for i in q["items"]]
    assert set(ids) == {news["doc_in"], news["doc_corr"], news["doc_out"], news["doc_filtered"]}
    assert news["doc_dup"] not in ids
    assert q["done"] == 0
    assert client.get("/labels/queue", params={"size": 10}).json()["items"][0]["document_id"] in ids
    doc = news["doc_filtered"]
    relevance = {"document_id": doc, "target_table": "documents", "target_id": doc}
    client.put("/labels", json=relevance | {"field": "relevant", "verdict": "correct"})
    stored = client.get("/labels", params={"document_id": doc}).json()
    assert stored[0]["judged_decision"] == "not_relevant"  # frozen at labeling time
    q = client.get("/labels/queue", params={"size": 10, "filtered_share": 0.5}).json()
    item = next(i for i in q["items"] if i["document_id"] == doc)
    assert (item["relevance_labeled"], item["n_records"], item["done"]) == (True, 0, True)
    assert q["done"] == 1


# --------------------------------------------------------------------------- reference


@pytest.mark.usefixtures("seeded")
def test_aoi_is_state_level_and_municipalities_are_separate(client: TestClient) -> None:
    aoi = client.get("/reference/aoi", params={"phase": 2}).json()["features"]
    assert {f["properties"]["area_type"] for f in aoi} == {"admin1"}
    assert len([f for f in aoi if f["properties"]["country_iso3"] == "MEX"]) == 32
    r = client.get("/reference/municipalities", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.json()["features"] == []  # gazetteer not loaded in this fixture
