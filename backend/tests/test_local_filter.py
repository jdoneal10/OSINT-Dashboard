from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, LLMQuarantine, Source
from app.enrich.infrastructure import infrastructure_match, keep_for_infrastructure
from app.enrich.local_filter import PROMPT_VERSION, LocalFilter, OllamaUnavailableError, run_filter


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
    assert counts == {"relevant": 2, "filtered_out": 1, "skipped": 1, "error": 0, "infra_kept": 0}
    seeded.expire_all()
    status = {d.id: d.pipeline_status for d in seeded.scalars(select(Document))}
    assert status == {a: "relevant", b: "filtered_out", c: "relevant", empty: "skipped"}
    doc = seeded.get_one(Document, a)
    assert doc.relevance_model == f"qwen3:4b/{PROMPT_VERSION}"
    assert calls[0]["think"] is False
    assert calls[0]["options"]["temperature"] == 0


def test_critical_infrastructure_is_kept_below_threshold(seeded: Session) -> None:
    """Owner rule (ADR 0012): criminal harm to infrastructure is kept whatever the model says."""
    pipe = _doc(seeded, "Toma clandestina en ducto de Pemex", text="Fuga en un ducto.")
    tower = _doc(seeded, "Armed men set fire to cell tower", text="Mobile service down.")
    leak = _doc(seeded, "Water main leak floods avenue", text="Crews repair the pipe.")
    plain = _doc(seeded, "Resultados del fútbol", text="Partido.")
    client = _ollama({}, [])  # every document scores 0.0
    counts = run_filter(local=LocalFilter(model="qwen3:4b", client=client))
    assert (counts["relevant"], counts["filtered_out"], counts["infra_kept"]) == (2, 2, 2)
    seeded.expire_all()
    for doc_id in (pipe, tower):
        doc = seeded.get_one(Document, doc_id)
        assert doc.pipeline_status == "relevant"
        assert doc.relevance_score == 0  # the model's own score is kept for evaluation
        assert doc.relevance_model == f"qwen3:4b/{PROMPT_VERSION}+infra-v2"
    for doc_id in (leak, plain):
        assert seeded.get_one(Document, doc_id).pipeline_status == "filtered_out"


@pytest.mark.parametrize(
    "text",
    [
        "Huachicol: toma clandestina found in Salamanca",  # inherently criminal
        "Robbery at Pemex gas station",
        "Hacking group breached data from Telmex",
        "Gunmen attack CFE substation crew",
        "Robo de cable de cobre deja sin luz a la colonia",
        "Explosivos colocados en torre de alta tensión",
    ],
)
def test_infrastructure_rule_keeps_criminal_harm(text: str) -> None:
    assert keep_for_infrastructure(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Water leak prompts traffic disruption on Avenida Toluca",  # routine utility incident
        "Truck crashes into utility pole prompting power outage",
        "Power outage planned for November 18 in Yucatan",
        "Eleven workers injured in incident at combined cycle power plant",
        "Hacking group breached Visit Puerto Vallarta",  # a place, not a port
        "Two hospitalized after gas explosion at residence",  # household gas
        "Laser strike reported near the border",  # a threat, but not infrastructure
    ],
)
def test_infrastructure_rule_skips_routine_incidents(text: str) -> None:
    assert not keep_for_infrastructure(text), text


def test_infrastructure_match_reports_its_terms() -> None:
    m = infrastructure_match("Robbery at Pemex gas station")
    assert m.sectors == {"energy": ["gas station", "pemex"]}
    assert (m.signals, m.always) == (["robbery"], [])


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
