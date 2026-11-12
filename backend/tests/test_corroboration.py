from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ClusterAssessment,
    Document,
    Event,
    EventCluster,
    LLMQuarantine,
    Source,
    event_documents,
)
from app.enrich import admiralty, analyze, dedupe, pipeline
from app.enrich.llm.client import Gateway

NOW = dt.datetime.now(dt.UTC)
TEXT = (
    "Un enfrentamiento entre dos grupos armados en la colonia centro dejó varios muertos y "
    "heridos, informaron autoridades estatales, que desplegaron un operativo en la zona tras "
    "reportes de disparos durante la madrugada del martes en el municipio. " * 3
)


def _source(session: Session, slug: str, grade: str) -> int:
    src = Source(slug=slug, name=slug.title(), source_type="rss", reliability=grade)
    session.add(src)
    session.flush()
    return src.id


def _doc(session: Session, sid: int, key: str, text: str = TEXT, status: str = "new") -> int:
    doc = Document(
        source_id=sid, source_key=key, retrieved_at=NOW, published_at=NOW, title=key,
        original_text=text, translated_text=f"Summary of {key}", pipeline_status=status,
    )  # fmt: skip
    session.add(doc)
    session.flush()
    return doc.id


def _event(
    session: Session, sid: int, doc_id: int | None, key: str, lon: float, lat: float,
    fatalities: int | None = 3, etype: str = "Battles", day: int = 10,
) -> int:  # fmt: skip
    ev = Event(
        source_id=sid, source_key=key, retrieved_at=NOW, event_date=dt.date(2026, 11, day),
        event_type=etype, fatalities=fatalities, admin1_code="MX-SIN", admin2_code="25006",
        geom=func.ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})"),
    )  # fmt: skip
    session.add(ev)
    session.flush()
    if doc_id is not None:
        session.execute(event_documents.insert().values(event_id=ev.id, document_id=doc_id))
    return ev.id


# --------------------------------------------------------------------------- documents


def test_simhash_distance() -> None:
    a = dedupe.simhash(TEXT)
    b = dedupe.simhash(TEXT.replace("martes", "miércoles", 1))
    c = dedupe.simhash("Resultados de la liga de fútbol y el clima del fin de semana. " * 6)
    assert dedupe.hamming(a, b) <= dedupe.SIMHASH_BITS
    assert dedupe.hamming(a, c) > 10


def test_syndicated_copy_marked_duplicate(seeded: Session) -> None:
    s1, s2 = _source(seeded, "out-a", "B"), _source(seeded, "out-b", "B")
    first = _doc(seeded, s1, "a")
    copy = _doc(seeded, s2, "b")
    other = _doc(seeded, s2, "c", text="Completely different story about elections. " * 10)
    assert dedupe.mark_duplicates(seeded) == 1
    assert seeded.get_one(Document, copy).duplicate_of_id == first
    assert seeded.get_one(Document, copy).pipeline_status == "skipped"
    assert seeded.get_one(Document, other).duplicate_of_id is None


# --------------------------------------------------------------------------- clusters


def test_clustering_counts_independent_sources_and_conflicts(seeded: Session) -> None:
    s1, s2 = _source(seeded, "out-a", "A"), _source(seeded, "out-b", "B")
    e1 = _event(seeded, s1, _doc(seeded, s1, "a"), "a:e0", -107.39, 24.80, fatalities=3)
    e2 = _event(seeded, s2, _doc(seeded, s2, "b"), "b:e0", -107.35, 24.79, fatalities=4,
                etype="Violence against civilians", day=11)  # fmt: skip
    far = _event(seeded, s2, _doc(seeded, s2, "c"), "c:e0", -106.40, 23.20)  # ~200 km away
    acled = seeded.scalars(select(Source.id).where(Source.slug == "acled")).one()
    acled_ev = _event(seeded, acled, None, "MEX-1", -107.39, 24.80)
    counts = dedupe.cluster_events(seeded)
    assert counts == {"new": 2, "joined": 1}
    c = seeded.get_one(Event, e1).cluster_id
    assert seeded.get_one(Event, e2).cluster_id == c
    assert seeded.get_one(Event, far).cluster_id not in (None, c)
    assert seeded.get_one(Event, acled_ev).cluster_id is None  # ACLED never clustered
    cluster = seeded.get_one(EventCluster, c)
    assert (cluster.n_events, cluster.n_documents, cluster.n_independent_sources) == (2, 2, 2)
    assert cluster.reliability == "A"
    assert cluster.conflicts["fatalities"] == [3, 4]
    assert (cluster.first_date, cluster.last_date) == (dt.date(2026, 11, 10), dt.date(2026, 11, 11))


def test_reextraction_prunes_and_invalidates_clusters(seeded: Session) -> None:
    cid, docs = _conflicted_cluster(seeded)
    seeded.add(ClusterAssessment(cluster_id=cid, judgment="old", cited_document_ids=docs))
    seeded.commit()
    # Re-extraction of one document deletes its event: the cluster shrinks, assessment drops.
    seeded.execute(delete(Event).where(Event.source_key == "b:e0"))
    dedupe.cluster_events(seeded)
    assert seeded.get_one(EventCluster, cid).n_events == 1
    assert seeded.scalar(select(func.count()).select_from(ClusterAssessment)) == 0
    # ...and when the last event goes, the cluster goes.
    seeded.execute(delete(Event).where(Event.source_key == "a:e0"))
    dedupe.cluster_events(seeded)
    assert seeded.get(EventCluster, cid) is None


@pytest.mark.parametrize(
    ("n", "grade", "conflicted", "expected"),
    [(3, "B", False, 1), (3, "B", True, 3), (2, "C", False, 2), (2, "A", True, 3),
     (1, "A", False, 2), (1, "B", False, 3), (1, "C", False, 4), (1, "E", False, 6),
     (0, None, False, 6)],
)  # fmt: skip
def test_admiralty_credibility(n: int, grade: str | None, conflicted: bool, expected: int) -> None:
    assert admiralty.credibility(n, grade, conflicted) == expected


def test_scores_propagate_to_events(seeded: Session) -> None:
    s1 = _source(seeded, "out-a", "B")
    e1 = _event(seeded, s1, _doc(seeded, s1, "a"), "a:e0", -107.39, 24.80)
    dedupe.cluster_events(seeded)
    admiralty.score_clusters(seeded)
    ev = seeded.get_one(Event, e1)
    assert (ev.credibility, str(ev.confidence)) == (3, "0.600")


# --------------------------------------------------------------------------- Sonnet


def _sonnet(payload: dict[str, Any]) -> Any:
    reply = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        stop_reason="end_turn", stop_details=None, model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=1500, output_tokens=300,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0),
        _request_id="req_s",
    )  # fmt: skip
    fake = SimpleNamespace(requests=[])
    fake.beta = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: fake.requests.append(kw) or reply)
    )
    return fake


def _conflicted_cluster(session: Session) -> tuple[int, list[int]]:
    s1, s2 = _source(session, "out-a", "A"), _source(session, "out-b", "B")
    d1, d2 = _doc(session, s1, "a"), _doc(session, s2, "b")
    _event(session, s1, d1, "a:e0", -107.39, 24.80, fatalities=3)
    _event(session, s2, d2, "b:e0", -107.38, 24.80, fatalities=5)
    dedupe.cluster_events(session)
    session.commit()
    cid = session.scalars(select(EventCluster.id)).one()
    return cid, [d1, d2]


def _assessment(cited: list[int]) -> dict[str, Any]:
    return {
        "same_incident": True,
        "judgment": "We assess it is likely that one clash occurred; counts differ.",
        "likelihood": "likely",
        "analytic_confidence": "moderate",
        "resolved": {"fatalities": 3, "municipality": "Culiacán", "event_type": "Battles"},
        "cited_document_ids": cited,
    }


def test_analysis_stores_cited_assessment(seeded: Session) -> None:
    cid, docs = _conflicted_cluster(seeded)
    fake = _sonnet(_assessment(docs))
    assert analyze.run_analyze(gateway=Gateway(fake)) == {"assessed": 1, "quarantined": 0}
    a = seeded.scalars(select(ClusterAssessment)).one()
    assert (a.cluster_id, a.likelihood, a.analytic_confidence) == (cid, "likely", "moderate")
    assert a.cited_document_ids == docs
    assert "[document" in fake.requests[0]["messages"][0]["content"]
    assert analyze.run_analyze(gateway=Gateway(fake)) == {"assessed": 0, "quarantined": 0}


def test_invented_citation_is_quarantined(seeded: Session) -> None:
    _conflicted_cluster(seeded)
    out = analyze.run_analyze(gateway=Gateway(_sonnet(_assessment([999_999]))))
    assert out == {"assessed": 0, "quarantined": 1}
    q = seeded.scalars(select(LLMQuarantine).where(LLMQuarantine.stage == "analyze")).one()
    assert "999999" in (q.error or "")


# --------------------------------------------------------------------------- pipeline


def test_pipeline_skips_unavailable_ollama(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "ollama_url", "http://127.0.0.1:9")  # nothing listens
    s1 = _source(seeded, "out-a", "B")
    _doc(seeded, s1, "a")
    seeded.commit()
    results = pipeline.run_pipeline(["dedupe", "filter", "cluster"])
    assert "skipped" in results["filter"]
    assert results["cluster"] == {"new": 0, "joined": 0, "scored": 0}
