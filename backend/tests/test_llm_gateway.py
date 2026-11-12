from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Alert,
    Document,
    Event,
    LLMQuarantine,
    LLMUsage,
    Source,
    event_documents,
)
from app.enrich.llm import client as gw
from app.enrich.llm.pricing import HAIKU, SONNET, cost_usd
from app.enrich.llm.schema import strict_schema


class Out(BaseModel):
    answer: str
    count: int | None = None


def _resp(text: str, *, stop: str = "end_turn", model: str = HAIKU, inp: int = 1000) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        stop_details=SimpleNamespace(category="general_harms") if stop == "refusal" else None,
        model=model,
        usage=SimpleNamespace(
            input_tokens=inp,
            output_tokens=200,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        _request_id="req_test",
    )


class FakeClient:
    """Records every request; replies from a queue."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.replies.pop(0)


def _call(gateway: gw.Gateway, prov: gw.Provenance, model: str = HAIKU) -> gw.LLMResult[Out]:
    return gateway.call(
        stage="extract",
        model=model,
        prompt_version="t1",
        system="Instruction block.",
        user="Article text.",
        output_model=Out,
        provenance=prov,
    )


@pytest.fixture
def news_doc(seeded: Session) -> int:
    src = Source(slug="test-news", name="Test News", source_type="rss", reliability="B")
    seeded.add(src)
    seeded.flush()
    doc = Document(
        source_id=src.id,
        source_key="https://news.example.org/a",
        retrieved_at=dt.datetime.now(dt.UTC),
        title="A",
        original_text="Synthetic text.",
    )
    seeded.add(doc)
    seeded.commit()
    return doc.id


def _acled_event(session: Session) -> int:
    sid = session.scalars(select(Source.id).where(Source.slug == "acled")).one()
    ev = Event(
        source_id=sid,
        source_key="MEX-T1",
        retrieved_at=dt.datetime.now(dt.UTC),
        event_date=dt.date(2026, 1, 1),
        event_type="Battles",
    )
    session.add(ev)
    session.commit()
    return ev.id


# --------------------------------------------------------------------------- licence guard


def test_acled_event_is_refused_before_sending(seeded: Session) -> None:
    fake = FakeClient(_resp('{"answer": "x", "count": 1}'))
    with pytest.raises(gw.LLMGuardError, match="acled"):
        _call(gw.Gateway(fake), gw.Provenance(event_ids=(_acled_event(seeded),)))
    assert fake.requests == []
    assert seeded.scalar(select(func.count()).select_from(LLMUsage)) == 0


def test_event_backed_by_acled_document_is_refused(seeded: Session, news_doc: int) -> None:
    acled = seeded.scalars(select(Source).where(Source.slug == "acled")).one()
    doc = seeded.get_one(Document, news_doc)
    doc.source_id = acled.id  # simulate ACLED-derived text stored as a document
    ev_src = seeded.scalars(select(Source.id).where(Source.slug == "test-news")).one()
    ev = Event(
        source_id=ev_src,
        source_key="news-ev-1",
        retrieved_at=dt.datetime.now(dt.UTC),
        event_date=dt.date(2026, 1, 1),
        event_type="Battles",
    )
    seeded.add(ev)
    seeded.flush()
    seeded.execute(event_documents.insert().values(event_id=ev.id, document_id=doc.id))
    seeded.commit()
    fake = FakeClient()
    with pytest.raises(gw.LLMGuardError):
        _call(gw.Gateway(fake), gw.Provenance(event_ids=(ev.id,)))
    assert fake.requests == []


def test_missing_provenance_is_refused() -> None:
    with pytest.raises(gw.LLMGuardError, match="provenance"):
        _call(gw.Gateway(FakeClient()), gw.Provenance())


# --------------------------------------------------------------------------- budget


def test_budget_pause_at_threshold_writes_one_alert(seeded: Session, news_doc: int) -> None:
    seeded.add(
        LLMUsage(stage="extract", model=HAIKU, prompt_version="t1", cost_usd=Decimal("60.00"))
    )  # 80% of the default $75 cap
    seeded.commit()
    fake = FakeClient()
    for _ in range(2):
        with pytest.raises(gw.BudgetPausedError):
            _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert fake.requests == []
    alerts = seeded.scalars(select(Alert).where(Alert.rule == "llm_budget_pause")).all()
    assert len(alerts) == 1


def test_below_threshold_proceeds(seeded: Session, news_doc: int) -> None:
    seeded.add(
        LLMUsage(stage="extract", model=HAIKU, prompt_version="t1", cost_usd=Decimal("59.99"))
    )
    seeded.commit()
    result = _call(gw.Gateway(FakeClient(_resp('{"answer": "ok", "count": 2}'))),
                   gw.Provenance(document_ids=(news_doc,)))  # fmt: skip
    assert result.ok


# --------------------------------------------------------------------------- validation path


def test_success_records_usage_and_sends_cached_strict_request(
    seeded: Session, news_doc: int
) -> None:
    fake = FakeClient(_resp('{"answer": "ok", "count": 2}'))
    result = _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert result.ok
    assert result.parsed == Out(answer="ok", count=2)
    req = fake.requests[0]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    schema = req["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["answer", "count"]
    row = seeded.scalars(select(LLMUsage)).one()
    assert (row.status, row.model, row.prompt_version, row.request_id) == (
        "ok",
        HAIKU,
        "t1",
        "req_test",
    )
    assert row.cost_usd == Decimal("0.000200")  # 1000 in x $0.10 + 200 out x $0.50 per MTok


def test_invalid_then_valid_retries_once(seeded: Session, news_doc: int) -> None:
    fake = FakeClient(_resp('{"answer": 5}'), _resp('{"answer": "fixed", "count": null}'))
    result = _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert (result.ok, result.attempts, len(result.usage_ids)) == (True, 2, 2)
    statuses = seeded.scalars(select(LLMUsage.status).order_by(LLMUsage.id)).all()
    assert statuses == ["invalid", "ok"]


def test_invalid_twice_is_quarantined(seeded: Session, news_doc: int) -> None:
    fake = FakeClient(_resp("not json"), _resp('{"wrong": true}'))
    result = _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert not result.ok
    assert result.parsed is None
    q = seeded.get_one(LLMQuarantine, result.quarantine_id)
    assert (q.reason, q.attempts, q.document_id, q.raw_output) == (
        "validation",
        2,
        news_doc,
        '{"wrong": true}',
    )


def test_refusal_is_quarantined_without_retry(seeded: Session, news_doc: int) -> None:
    fake = FakeClient(_resp("", stop="refusal"))
    result = _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert (result.ok, result.attempts) == (False, 1)
    q = seeded.get_one(LLMQuarantine, result.quarantine_id)
    assert q.reason == "refusal"
    assert "general_harms" in (q.error or "")


def test_truncation_retries_with_more_tokens(seeded: Session, news_doc: int) -> None:
    fake = FakeClient(_resp('{"answ', stop="max_tokens"), _resp('{"answer": "ok", "count": 1}'))
    result = _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)))
    assert result.ok
    assert [r["max_tokens"] for r in fake.requests] == [8000, 16000]


def test_sonnet_uses_server_side_refusal_fallback(seeded: Session, news_doc: int) -> None:
    fake = FakeClient(_resp('{"answer": "ok", "count": 1}', model=SONNET))
    _call(gw.Gateway(fake), gw.Provenance(document_ids=(news_doc,)), model=SONNET)
    req = fake.requests[0]
    assert req["betas"] == [gw.FALLBACK_BETA]
    assert req["fallbacks"] == "default"


# --------------------------------------------------------------------------- pricing / schema


def test_pricing() -> None:
    assert cost_usd(SONNET, input_tokens=1_000_000, output_tokens=100_000) == Decimal("3.000000")
    assert cost_usd(SONNET, input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000) == (
        Decimal("0.100000")
    )
    # Haiku prompts above 100K tokens use the long-context tier.
    assert cost_usd(HAIKU, input_tokens=200_000, output_tokens=0) == Decimal("0.100000")
    assert cost_usd(HAIKU, input_tokens=1_000_000, output_tokens=0, batch=True) == Decimal(
        "0.250000"
    )


def test_strict_schema_nested() -> None:
    class Inner(BaseModel):
        x: int
        y: str | None = None

    class Outer(BaseModel):
        items: list[Inner]

    schema = strict_schema(Outer)
    inner = schema["$defs"]["Inner"]
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["x", "y"]
    assert "title" not in inner


def test_client_pins_official_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.invalid")
    monkeypatch.setattr(gw, "require_secret", lambda _name: SecretStr("sk-test-not-real"))
    client = gw.Gateway().client
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"


def test_strict_schema_moves_unsupported_constraints_to_description() -> None:
    class C(BaseModel):
        n: int | None = Field(ge=0)
        items: list[str] = Field(max_length=10, description="Things")
        ids: list[int] = Field(min_length=1)

    schema = strict_schema(C)
    text = str(schema)
    for banned in ("minimum", "maxItems", "maxLength", "exclusiveMinimum"):
        assert banned not in text
    assert schema["properties"]["items"]["description"] == "Things (at most items: 10)"
    assert schema["properties"]["ids"]["minItems"] == 1
    assert ">= 0" in str(schema["properties"]["n"])
