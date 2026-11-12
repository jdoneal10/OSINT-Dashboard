from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, LLMQuarantine, Source
from app.enrich.local_filter import LocalFilter, OllamaUnavailableError, run_filter


def _ollama(scores: dict[str, Any], calls: list[dict[str, Any]]) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body)
        text = body["messages"][1]["content"]
        reply = next((v for k, v in scores.items() if k in text), {"relevance": 0.0, "reason": "-"})
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _doc(session: Session, title: str, text: str | None = "body") -> int:
    src = session.scalars(select(Source).where(Source.slug == "t-news")).one_or_none()
    if src is None:
        src = Source(slug="t-news", name="T", source_type="rss", reliability="B")
        session.add(src)
        session.flush()
    doc = Document(
        source_id=src.id,
        source_key=title,
        retrieved_at=dt.datetime.now(dt.UTC),
        title=title if text is not None else None,
        original_text=text,
    )
    session.add(doc)
    session.commit()
    return doc.id


def test_scores_and_routes_documents(seeded: Session) -> None:
    a = _doc(seeded, "Enfrentamiento entre cárteles")
    b = _doc(seeded, "Resultados del fútbol")
    c = _doc(seeded, "Borderline report")
    empty = _doc(seeded, "", text=None)
    calls: list[dict[str, Any]] = []
    client = _ollama(
        {
            "cárteles": {"relevance": 0.95, "reason": "cartel clash"},
            "fútbol": {"relevance": 0.02, "reason": "sports"},
            "Borderline": {"relevance": 0.3, "reason": "maybe"},
        },
        calls,
    )
    counts = run_filter(local=LocalFilter(model="qwen3:4b", client=client))
    assert counts == {"relevant": 2, "filtered_out": 1, "skipped": 1, "error": 0}
    seeded.expire_all()
    status = {d.id: d.pipeline_status for d in seeded.scalars(select(Document))}
    assert status == {a: "relevant", b: "filtered_out", c: "relevant", empty: "skipped"}
    doc = seeded.get_one(Document, a)
    assert doc.relevance_model == "qwen3:4b/filter-v1"
    assert calls[0]["think"] is False
    assert calls[0]["options"]["temperature"] == 0


def test_malformed_output_is_quarantined(seeded: Session) -> None:
    d = _doc(seeded, "Garbage reply")
    client = _ollama({"Garbage": "not json at all"}, [])
    counts = run_filter(local=LocalFilter(model="qwen3:4b", client=client))
    assert counts["error"] == 1
    q = seeded.scalars(select(LLMQuarantine)).one()
    assert (q.stage, q.document_id) == ("filter", d)


def test_missing_model_gives_actionable_error() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
    with pytest.raises(OllamaUnavailableError, match="ollama pull"):
        LocalFilter(model="qwen3:4b", client=client).score("x")


def test_long_reason_is_truncated_not_rejected() -> None:
    reply = json.dumps({"relevance": 0.9, "reason": "x" * 1000})
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"message": {"content": reply}})
        )
    )
    out = LocalFilter(model="qwen3:4b", client=client).score("text")
    assert out.relevance == 0.9
    assert len(out.reason) == 300
