"""The single gateway to Claude. Every model call in this project goes through ``Gateway.call``.

Guards (ADR 0003, ADR 0004):

1. **ACLED exclusion.** Callers must declare the provenance of everything in the prompt
   (document and/or event ids). The gateway looks up their sources in the database, including
   the documents behind each event, and raises ``LLMGuardError`` *before any request is sent*
   if any of them is in ``BLOCKED_SOURCES``. A call with no declared provenance is refused.
2. **Budget.** Month-to-date spend (``llm_usage``) is checked before every call. At
   ``llm_budget_alert_fraction`` of ``llm_monthly_budget_usd`` the API stages pause
   (``BudgetPausedError``) and one ``alerts`` row is written for the month.
3. **Validation.** Output is requested as strict JSON (``output_config.format``) and validated
   by the pydantic model. Invalid output is retried once, then quarantined; refusals and
   truncated output go straight to quarantine. Nothing unvalidated reaches core tables.
4. **Ledger.** Every API attempt writes an ``llm_usage`` row (model, prompt_version, tokens,
   cost, request id, status), successful or not.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.secrets import require_secret
from app.db.models import Alert, Document, Event, LLMQuarantine, LLMUsage, Source, event_documents
from app.db.session import session_factory
from app.enrich.llm.pricing import PRICES, SONNET, cost_usd
from app.enrich.llm.schema import strict_schema

log = logging.getLogger(__name__)

BLOCKED_SOURCES = frozenset({"acled"})  # licence: ACLED EULA s.7.1 (ADR 0003)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMGuardError(RuntimeError):
    """The request was refused before sending (licence guard or missing provenance)."""


class BudgetPausedError(RuntimeError):
    """Month-to-date LLM spend reached the pause threshold; API stages are paused."""


@dataclass(frozen=True)
class Provenance:
    """Records whose content is in the prompt. Must not be empty."""

    document_ids: tuple[int, ...] = ()
    event_ids: tuple[int, ...] = ()
    cluster_id: int | None = None

    @property
    def empty(self) -> bool:
        return not self.document_ids and not self.event_ids


@dataclass
class LLMResult[T: BaseModel]:
    ok: bool
    parsed: T | None
    model: str
    prompt_version: str
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    usage_ids: list[int] = field(default_factory=list)
    quarantine_id: int | None = None


# --------------------------------------------------------------------------- guards


def provenance_sources(session: Session, prov: Provenance) -> set[str]:
    """Slugs of every source behind the declared records (events include their documents)."""
    slugs: set[str] = set()
    if prov.document_ids:
        slugs |= set(
            session.scalars(
                select(Source.slug)
                .join(Document, Document.source_id == Source.id)
                .where(Document.id.in_(prov.document_ids))
            )
        )
    if prov.event_ids:
        slugs |= set(
            session.scalars(
                select(Source.slug)
                .join(Event, Event.source_id == Source.id)
                .where(Event.id.in_(prov.event_ids))
            )
        )
        slugs |= set(
            session.scalars(
                select(Source.slug)
                .join(Document, Document.source_id == Source.id)
                .join(event_documents, event_documents.c.document_id == Document.id)
                .where(event_documents.c.event_id.in_(prov.event_ids))
            )
        )
    return slugs


def check_provenance(session: Session, prov: Provenance) -> None:
    if prov.empty:
        raise LLMGuardError("LLM call refused: provenance (document/event ids) must be declared")
    blocked = provenance_sources(session, prov) & BLOCKED_SOURCES
    if blocked:
        raise LLMGuardError(
            f"LLM call refused: input derives from {sorted(blocked)}, which may not be sent "
            "to an LLM (licence; ADR 0003)"
        )


def month_start(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_to_date_spend(session: Session) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(LLMUsage.cost_usd), 0)).where(
            LLMUsage.called_at >= month_start()
        )
    )
    return Decimal(total or 0)


def budget_status(session: Session) -> dict[str, Any]:
    settings = get_settings()
    cap = Decimal(str(settings.llm_monthly_budget_usd))
    threshold = cap * Decimal(str(settings.llm_budget_alert_fraction))
    spent = month_to_date_spend(session)
    return {"spent": spent, "cap": cap, "threshold": threshold, "paused": spent >= threshold}


def check_budget(session: Session) -> None:
    status = budget_status(session)
    if not status["paused"]:
        return
    month = month_start().strftime("%Y-%m")
    already = session.scalar(
        select(Alert.id).where(
            Alert.rule == "llm_budget_pause", Alert.linked_records["month"].astext == month
        )
    )
    if already is None:
        session.add(
            Alert(
                rule="llm_budget_pause",
                severity=3,
                summary=(
                    f"LLM spend ${status['spent']:.2f} reached the pause threshold"
                    f" (${status['threshold']:.2f} of the ${status['cap']:.2f} monthly cap);"
                    " API stages paused until next month or until the cap is raised."
                ),
                linked_records={"month": month, "spent": str(status["spent"])},
            )
        )
        session.commit()
        log.warning("LLM budget pause: $%s of $%s", status["spent"], status["cap"])
    raise BudgetPausedError(f"LLM budget paused: ${status['spent']} spent of ${status['cap']}")


# --------------------------------------------------------------------------- gateway


class Gateway:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=require_secret("ANTHROPIC_API_KEY").get_secret_value()
            )
        return self._client

    def _send(self, kwargs: dict[str, Any], model: str) -> Any:
        if model == SONNET:
            # Server-side refusal fallback (ADR 0004); only offered on the beta surface.
            return self.client.beta.messages.create(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        return self.client.messages.create(**kwargs)

    def _record(
        self, session: Session, *, stage: str, model: str, prompt_version: str, resp: Any,
        status: str,
    ) -> LLMUsage:  # fmt: skip
        usage = resp.usage
        served = getattr(resp, "model", model) or model
        price_model = served if served in PRICES else model
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        row = LLMUsage(
            stage=stage,
            model=served,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            batch=False,
            cost_usd=cost_usd(
                price_model,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_write_tokens=cache_write,
                cache_read_tokens=cache_read,
            ),
            status=status,
            request_id=getattr(resp, "_request_id", None),
        )
        session.add(row)
        session.flush()
        return row

    def _quarantine(
        self, session: Session, *, stage: str, model: str, prompt_version: str,
        prov: Provenance, reason: str, error: str | None, raw: str | None, attempts: int,
    ) -> int:  # fmt: skip
        row = LLMQuarantine(
            stage=stage,
            document_id=prov.document_ids[0] if prov.document_ids else None,
            cluster_id=prov.cluster_id,
            model=model,
            prompt_version=prompt_version,
            reason=reason,
            error=(error or "")[:4000] or None,
            raw_output=(raw or "")[:100_000] or None,
            attempts=attempts,
        )
        session.add(row)
        session.flush()
        return row.id

    def call[T: BaseModel](
        self,
        *,
        stage: str,
        model: str,
        prompt_version: str,
        system: str,
        user: str,
        output_model: type[T],
        provenance: Provenance,
        max_tokens: int = 8000,
        effort: str | None = None,
    ) -> LLMResult[T]:
        """One validated structured call. Guards run first; nothing is sent if they fail."""
        with session_factory()() as session:
            check_provenance(session, provenance)
            check_budget(session)

        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": strict_schema(output_model)}
        }
        if effort:
            output_config["effort"] = effort
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            # Stable instruction block first, cached (ADR 0004); per-document text after it.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        result: LLMResult[T] = LLMResult(
            ok=False, parsed=None, model=model, prompt_version=prompt_version
        )
        last_error: str | None = None
        raw: str | None = None
        reason = "validation"
        for attempt in (1, 2):
            resp = self._send(kwargs, model)
            result.attempts = attempt
            stop = getattr(resp, "stop_reason", None)
            raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
            status = "ok"
            if stop == "refusal":
                status, reason = "refusal", "refusal"
                details = getattr(resp, "stop_details", None)
                last_error = f"refusal: {getattr(details, 'category', None)}"
            elif stop == "max_tokens":
                status, reason, last_error = "max_tokens", "max_tokens", "output truncated"
            else:
                try:
                    parsed = output_model.model_validate_json(raw or "")
                except ValidationError as exc:
                    status, reason, last_error = "invalid", "validation", str(exc)
                else:
                    result.parsed, result.ok = parsed, True
            with session_factory()() as session, session.begin():
                usage = self._record(
                    session, stage=stage, model=model, prompt_version=prompt_version, resp=resp,
                    status=status,
                )  # fmt: skip
                result.usage_ids.append(usage.id)
            result.input_tokens += resp.usage.input_tokens or 0
            result.output_tokens += resp.usage.output_tokens or 0
            if result.ok or reason == "refusal":
                break  # a refusal will not change on retry
            if reason == "max_tokens":
                kwargs["max_tokens"] = min(kwargs["max_tokens"] * 2, 32_000)
        if not result.ok:
            with session_factory()() as session, session.begin():
                result.quarantine_id = self._quarantine(
                    session, stage=stage, model=model, prompt_version=prompt_version,
                    prov=provenance, reason=reason, error=last_error, raw=raw,
                    attempts=result.attempts,
                )  # fmt: skip
            log.warning(
                "%s quarantined (%s) after %d attempt(s): %s",
                stage, reason, result.attempts, (last_error or "")[:200],
            )  # fmt: skip
        return result
