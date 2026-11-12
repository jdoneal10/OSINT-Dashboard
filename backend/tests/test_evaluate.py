from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.db.models import Document, Event, Label, Seizure, Source, event_documents
from app.enrich import evaluate
from app.enrich.local_filter import FilterOutput

NOW = dt.datetime(2026, 11, 10, tzinfo=dt.UTC)
V = "extract-v3"


def _doc(session: Session, sid: int, key: str, status: str, score: str) -> int:
    doc = Document(
        source_id=sid,
        source_key=key,
        retrieved_at=NOW,
        title=key,
        original_text=f"text {key}",
        pipeline_status=status,
        relevance_score=Decimal(score),
    )
    session.add(doc)
    session.flush()
    return doc.id


def _event(session: Session, sid: int, doc_id: int, key: str) -> int:
    ev = Event(source_id=sid, source_key=key, retrieved_at=NOW, event_date=NOW.date(),
               event_type="Battles", prompt_version=V)  # fmt: skip
    session.add(ev)
    session.flush()
    session.execute(event_documents.insert().values(event_id=ev.id, document_id=doc_id))
    return ev.id


def _label(session: Session, doc: int, table: str, target: int, verdict: str, field: str = "",
           version: str = V) -> None:  # fmt: skip
    session.add(Label(document_id=doc, target_table=table, target_id=target, field=field,
                      verdict=verdict, prompt_version=version))  # fmt: skip
    session.flush()


@pytest.fixture
def source(seeded: Session) -> int:
    src = Source(slug="news-a", name="News A", source_type="rss", reliability="B")
    seeded.add(src)
    seeded.flush()
    return src.id


def test_wilson_interval() -> None:
    lo, hi = evaluate.wilson(85, 100)
    assert (round(lo, 3), round(hi, 3)) == (0.767, 0.907)
    assert evaluate.wilson(0, 0) == (0.0, 0.0)


def test_record_precision_strict_lenient_fields_and_versions(seeded: Session, source: int) -> None:
    d1 = _doc(seeded, source, "a", "extracted", "0.9")
    d2 = _doc(seeded, source, "b", "extracted", "0.8")
    e1, e2, e3, e4, e5 = (_event(seeded, source, d1, f"a:e{i}") for i in range(5))
    sz = Seizure(source_id=source, source_key="b:s0", retrieved_at=NOW,
                 seizure_date=NOW.date(), substance="fentanyl", prompt_version=V)  # fmt: skip
    seeded.add(sz)
    seeded.flush()
    _label(seeded, d1, "events", e1, "correct")
    _label(seeded, d1, "events", e2, "partial", "fatalities,person_named")
    _label(seeded, d1, "events", e3, "incorrect")
    _label(seeded, d2, "seizures", sz.id, "correct")
    _label(seeded, d1, "events", e4, "incorrect", version="extract-v1")  # other prompt: ignored
    _label(seeded, d1, "events", e5, "partial", "out_of_aoi")  # scope only: counts as correct
    seeded.commit()

    rec = evaluate.record_precision(seeded, V)
    assert (rec.overall.n, rec.overall.correct, rec.overall.partial) == (5, 3, 1)
    assert rec.overall.strict == 0.6
    assert rec.overall.lenient == 0.8
    assert rec.out_of_aoi == 1
    assert rec.by_table["seizures"].strict == 1.0
    assert rec.field_errors == {"fatalities": 1, "person_named": 1}
    assert rec.person_named == 1
    assert rec.documents == 2
    assert rec.wrong_records == [("events", e2), ("events", e3)]


def test_filter_recall_is_weighted_by_stratum(seeded: Session, source: int) -> None:
    # Corpus: 8 documents passed the filter (score >= 0.3), 4 were rejected.
    passed = [_doc(seeded, source, f"p{i}", "extracted", "0.8") for i in range(8)]
    rejected = [_doc(seeded, source, f"r{i}", "filtered_out", "0.1") for i in range(4)]
    # Labeled: 2 passed (both right), 2 rejected (one was actually relevant: a filter miss).
    for d in passed[:2]:
        _label(seeded, d, "documents", d, "correct", "relevant")
    _label(seeded, rejected[0], "documents", rejected[0], "correct", "relevant")
    _label(seeded, rejected[1], "documents", rejected[1], "incorrect", "relevant")
    seeded.commit()

    docs = evaluate.judged_documents(seeded, 0.3)
    weights = {d.document_id: d.weight for d in docs}
    assert weights[passed[0]] == 4.0  # 8 in corpus / 2 labeled
    assert weights[rejected[0]] == 2.0  # 4 / 2
    m = evaluate.filter_metrics(docs, {d.document_id: d.score for d in docs}, "qwen", 0.3)
    # Truly relevant weight: 2 x 4 (passed) + 1 x 2 (missed) = 10; caught 8.
    assert m.recall == pytest.approx(0.8)
    assert m.precision == pytest.approx(1.0)
    assert m.pass_rate == pytest.approx(8 / 12)
    sweep = dict((t, r) for t, r, _ in m.sweep)
    assert sweep[0.1] == pytest.approx(1.0)  # the miss scored 0.1


def test_relevance_label_keeps_the_decision_it_judged(seeded: Session, source: int) -> None:
    doc = _doc(seeded, source, "x", "filtered_out", "0.1")
    seeded.add(
        Label(
            document_id=doc,
            target_table="documents",
            target_id=doc,
            field="relevant",
            verdict="incorrect",
            judged_decision="not_relevant",
        )
    )
    seeded.commit()
    # Later re-filtering passes the document; the label still means "this was relevant".
    seeded.get_one(Document, doc).pipeline_status = "extracted"
    seeded.commit()
    (judged,) = evaluate.judged_documents(seeded, 0.3)
    assert judged.truly_relevant is True


class FakeScorer:
    model = "fake"

    def score(self, text: str) -> FilterOutput:
        return FilterOutput(relevance=0.9 if text.endswith("r1") else 0.2, reason="x")


def test_model_comparison_and_report(seeded: Session, source: int, tmp_path: Path) -> None:
    d = _doc(seeded, source, "p0", "extracted", "0.8")
    miss = _doc(seeded, source, "r1", "filtered_out", "0.1")
    _label(seeded, d, "documents", d, "correct", "relevant")
    _label(seeded, miss, "documents", miss, "incorrect", "relevant")
    e = _event(seeded, source, d, "p0:e0")
    _label(seeded, d, "events", e, "correct")
    seeded.commit()

    path = evaluate.run(
        compare_models=["fake"],
        out_dir=tmp_path,
        today=dt.date(2026, 11, 11),
        scorer_factory=lambda _m: SimpleNamespace(score=FakeScorer().score),  # type: ignore[arg-type,return-value]
    )
    assert path.name == f"2026-11-11-extraction-{V}.md"
    text = path.read_text()
    assert "INSUFFICIENT SAMPLE" in text
    assert "| events | 1 | 1 | 0 | 0 | 100.0% |" in text
    assert "| fake | 0.30 |" in text
    assert "text p0" not in text  # article text never lands in the report
