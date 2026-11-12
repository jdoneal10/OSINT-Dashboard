from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Document, Label, LLMBatch, LLMQuarantine, LLMUsage
from app.enrich import extract
from app.enrich.llm.client import Gateway
from app.enrich.llm.pricing import HAIKU
from tests.test_extract import GOOD, _resp, doc_id  # noqa: F401 — doc_id is a fixture

pytestmark = pytest.mark.usefixtures("doc_id")


def _refusal() -> Any:
    r = _resp("")
    r.stop_reason = "refusal"
    r.stop_details = SimpleNamespace(category="general_harms")
    return r


class FakeBatches:
    """messages.batches.{create,retrieve,results} plus messages.create for retries."""

    def __init__(self, *retry_replies: Any) -> None:
        self.created: list[list[dict[str, Any]]] = []
        self.status = "in_progress"
        self.outcomes: dict[str, Any] = {}
        self.retry_replies = list(retry_replies)
        self.retries: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(
            create=self._create,
            batches=SimpleNamespace(
                create=self._batch_create, retrieve=self._retrieve, results=self._results
            ),
        )

    def _create(self, **kw: Any) -> Any:
        self.retries.append(kw)
        return self.retry_replies.pop(0)

    def _batch_create(self, *, requests: list[dict[str, Any]]) -> Any:
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def _retrieve(self, batch_id: str) -> Any:
        counts = SimpleNamespace(processing=0, succeeded=len(self.outcomes), errored=0,
                                 canceled=0, expired=0)  # fmt: skip
        return SimpleNamespace(id=batch_id, processing_status=self.status, request_counts=counts)

    def _results(self, batch_id: str) -> list[Any]:
        return [SimpleNamespace(custom_id=cid, result=r) for cid, r in self.outcomes.items()]


def ok(resp: Any) -> Any:
    return SimpleNamespace(type="succeeded", message=resp)


def errored() -> Any:
    return SimpleNamespace(type="errored", error=SimpleNamespace(type="api_error"))


@pytest.fixture
def three_docs(seeded: Session, doc_id: int, monkeypatch: pytest.MonkeyPatch) -> list[int]:  # noqa: F811
    """Three relevant documents and a batch threshold of 3."""
    monkeypatch.setattr(get_settings(), "llm_batch_threshold", 3)
    first = seeded.get_one(Document, doc_id)
    ids = [doc_id]
    for n in (2, 3):
        d = Document(source_id=first.source_id, source_key=f"https://full.example.org/{n}",
                     retrieved_at=dt.datetime.now(dt.UTC), title=f"Doc {n}",
                     original_text=first.original_text, pipeline_status="relevant")  # fmt: skip
        seeded.add(d)
        seeded.flush()
        ids.append(d.id)
    seeded.commit()
    return ids


def _statuses(session: Session, ids: list[int]) -> list[str]:
    session.expire_all()
    return [session.get_one(Document, i).pipeline_status for i in ids]


def test_small_backlog_stays_real_time(seeded: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "llm_batch_threshold", 5)
    fake = FakeBatches(_resp(GOOD))
    counts = extract.run_extract(gateway=Gateway(fake))
    assert counts["extracted"] == 1
    assert fake.created == []


def test_backlog_is_submitted_as_one_guarded_batch(seeded: Session, three_docs: list[int]) -> None:
    fake = FakeBatches()
    assert extract.run_extract(gateway=Gateway(fake)) == {"batched": 3}
    (requests,) = fake.created
    assert sorted(r["custom_id"] for r in requests) == sorted(f"doc-{i}" for i in three_docs)
    params = requests[0]["params"]
    assert params["model"] == HAIKU
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "stream" not in params
    assert "fallbacks" not in params
    assert _statuses(seeded, three_docs) == ["batched"] * 3
    row = seeded.scalars(select(LLMBatch)).one()
    assert (row.status, row.n_requests, row.prompt_version) == (
        "submitted",
        3,
        extract.PROMPT_VERSION,
    )
    assert row.estimated_cost_usd > 0
    assert fake.retries == []  # nothing sent in real time


def test_collect_stores_retries_once_then_quarantines(
    seeded: Session, three_docs: list[int]
) -> None:
    a, b, c = three_docs
    fake = FakeBatches(_resp(GOOD), _resp("not json"))  # real-time retries for b, then c
    extract.run_extract(gateway=Gateway(fake))
    assert extract.run_collect(gateway=Gateway(fake))["pending"] == 1  # still running

    fake.status = "ended"
    fake.outcomes = {f"doc-{a}": ok(_resp(GOOD)), f"doc-{b}": ok(_resp('{"bad": 1}')),
                     f"doc-{c}": errored()}  # fmt: skip
    counts = extract.run_collect(gateway=Gateway(fake))
    assert {k: counts[k] for k in ("batches", "ok", "retried_ok", "quarantined")} == {
        "batches": 1, "ok": 1, "retried_ok": 1, "quarantined": 1,
    }  # fmt: skip
    assert _statuses(seeded, three_docs) == ["extracted", "extracted", "quarantined"]
    assert len(fake.retries) == 2  # one real-time retry each for b and c
    usage = seeded.scalars(select(LLMUsage).order_by(LLMUsage.id)).all()
    assert [(u.batch, u.status) for u in usage] == [
        (True, "ok"), (True, "invalid"), (False, "ok"), (False, "invalid"),
    ]  # fmt: skip
    # Batch results cost half the real-time price for the same tokens.
    assert abs(usage[0].cost_usd * 2 - usage[2].cost_usd) <= Decimal("0.000002")  # rounding
    q = seeded.scalars(select(LLMQuarantine)).one()
    assert (q.document_id, q.attempts) == (c, 2)
    assert seeded.scalars(select(LLMBatch)).one().status == "collected"
    assert extract.run_collect(gateway=Gateway(fake))["batches"] == 0  # collected once


def test_batch_refusal_is_quarantined_without_retry(seeded: Session, three_docs: list[int]) -> None:
    fake = FakeBatches()
    extract.run_extract(gateway=Gateway(fake))
    fake.status = "ended"
    fake.outcomes = {f"doc-{i}": ok(_refusal()) for i in three_docs}
    assert extract.run_collect(gateway=Gateway(fake))["quarantined"] == 3
    assert fake.retries == []
    assert {q.reason for q in seeded.scalars(select(LLMQuarantine))} == {"refusal"}


def test_budget_pause_blocks_submission(seeded: Session, three_docs: list[int]) -> None:
    seeded.add(LLMUsage(stage="extract", model=HAIKU, prompt_version="v", cost_usd=Decimal("60")))
    seeded.commit()
    fake = FakeBatches()
    assert extract.run_extract(gateway=Gateway(fake)) == {"batched": 0}
    assert fake.created == []
    assert _statuses(seeded, three_docs) == ["relevant"] * 3


def test_prompt_change_while_running_requeues(
    seeded: Session, three_docs: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBatches()
    extract.run_extract(gateway=Gateway(fake))
    monkeypatch.setattr(extract, "PROMPT_VERSION", "extract-vNEXT")
    fake.status = "ended"
    fake.outcomes = {f"doc-{i}": ok(_resp(GOOD)) for i in three_docs}
    assert extract.run_collect(gateway=Gateway(fake))["requeued"] == 3
    assert _statuses(seeded, three_docs) == ["relevant"] * 3


def test_reextraction_skips_labeled_and_unseen_documents(
    seeded: Session,
    three_docs: list[int],
) -> None:
    a, b, c = three_docs
    for target, status, version in (
        (a, "extracted", "extract-v1"),
        (b, "filtered_out", "extract-v1"),  # Haiku said no
        (c, "filtered_out", None),
    ):  # local filter said no
        doc = seeded.get_one(Document, target)
        doc.pipeline_status, doc.prompt_version = status, version
    labeled = Document(source_id=seeded.get_one(Document, a).source_id, source_key="lab",
                       retrieved_at=dt.datetime.now(dt.UTC), pipeline_status="extracted",
                       prompt_version="extract-v1")  # fmt: skip
    seeded.add(labeled)
    seeded.flush()
    seeded.add(Label(document_id=labeled.id, target_table="events", target_id=1,
                     verdict="correct"))  # fmt: skip
    seeded.commit()
    assert extract.mark_for_reextraction() == 2
    assert _statuses(seeded, [a, b, c, labeled.id]) == [
        "relevant", "relevant", "filtered_out", "extracted",
    ]  # fmt: skip
    assert json.dumps(GOOD)  # fixture sanity
