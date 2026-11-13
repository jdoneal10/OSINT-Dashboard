"""Message Batches API: half-price processing for backlogs (CLAUDE.md LLM pipeline rules).

Used for backfills and re-extraction after a prompt change, where results can wait (most
batches finish within an hour; at most 24 h). The same guarantees as real-time calls apply:

- **Guards at submission.** Every request's provenance passes the licence guard, the budget
  must not be paused, and the batch is trimmed so its estimated cost stays under the pause
  threshold. Nothing is submitted if a guard fails.
- **Validation at collection.** Each result is checked against the output schema like a
  real-time response and logged to ``llm_usage`` (``batch = true``, billed at 50%).
- **One retry, then quarantine.** A result that is invalid, truncated, errored or expired
  counts as the first attempt and gets one real-time retry; refusals are not retried.

``submit`` and ``collect`` take a ``BatchJob``: the stage-specific request builder and the
store/fail callbacks (see ``app.enrich.extract``).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import LLMBatch
from app.db.session import session_factory
from app.enrich.llm.client import (
    BudgetPausedError,
    Gateway,
    LLMResult,
    Provenance,
    assess,
    budget_status,
    check_budget,
    check_provenance,
    request_params,
)
from app.enrich.llm.pricing import PRICES

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3.5  # conservative for Spanish/English prose
EST_OUTPUT_TOKENS = 1500  # typical extraction output; max_tokens is only a ceiling


@dataclass(frozen=True)
class BatchItem:
    custom_id: str
    document_id: int
    user: str
    provenance: Provenance


@dataclass
class BatchJob[T: BaseModel]:
    """Everything stage-specific about a batch."""

    stage: str
    model: str
    prompt_version: str
    system: str
    output_model: type[T]
    max_tokens: int
    effort: str | None
    # Rebuild a request for the real-time retry (the batch keeps no prompt text).
    rebuild: Callable[[int], BatchItem]
    # Store a validated result: (document_id, parsed, (input_tokens, output_tokens)).
    store: Callable[[int, T, tuple[int, int]], None]
    # Mark a document whose request could not be completed.
    fail: Callable[[int], None]
    # Return a document to the queue (budget paused before its retry).
    requeue: Callable[[int], None]


def estimate_cost(job: BatchJob[Any], items: Sequence[BatchItem]) -> Decimal:
    """Upper-ish estimate at batch prices: prompt characters plus typical output."""
    price = PRICES[job.model]
    tokens_in = sum(len(job.system) + len(i.user) for i in items) / CHARS_PER_TOKEN
    tokens_out = len(items) * EST_OUTPUT_TOKENS
    per_mtok = Decimal(1_000_000)
    cost = (
        Decimal(str(tokens_in)) * price.input / per_mtok
        + Decimal(tokens_out) * price.output / per_mtok
    )
    return (cost / 2).quantize(Decimal("0.000001"))


def submit(gateway: Gateway, job: BatchJob[Any], items: Sequence[BatchItem]) -> LLMBatch | None:
    """Submit up to ``items`` as one batch. Returns the batch row, or None if nothing to do.

    Raises ``LLMGuardError`` / ``BudgetPausedError`` before anything is sent.
    """
    if not items:
        return None
    with session_factory()() as session:
        for item in items:
            check_provenance(session, item.provenance)
        check_budget(session)
        status = budget_status(session)
    headroom = status["threshold"] - status["spent"]
    chosen = list(items)
    while chosen and estimate_cost(job, chosen) > headroom:
        chosen = chosen[: len(chosen) * 3 // 4]  # trim to fit under the pause threshold
    if not chosen:
        raise BudgetPausedError("batch would exceed the LLM budget pause threshold")
    requests = [
        {
            "custom_id": item.custom_id,
            "params": request_params(
                model=job.model,
                system=job.system,
                user=item.user,
                output_model=job.output_model,
                max_tokens=job.max_tokens,
                effort=job.effort,
            ),
        }
        for item in chosen
    ]
    created = gateway.client.messages.batches.create(requests=requests)
    with session_factory()() as session, session.begin():
        row = LLMBatch(
            anthropic_batch_id=created.id,
            stage=job.stage,
            model=job.model,
            prompt_version=job.prompt_version,
            status="submitted",
            n_requests=len(chosen),
            items={i.custom_id: i.document_id for i in chosen},
            estimated_cost_usd=estimate_cost(job, chosen),
        )
        session.add(row)
    log.info(
        "%s batch %s submitted: %d requests (est. $%s)",
        job.stage, created.id, len(chosen), row.estimated_cost_usd,
    )  # fmt: skip
    return row


def _retry(gateway: Gateway, job: BatchJob[Any], document_id: int, counts: dict[str, int]) -> None:
    """One real-time retry after a failed batch result; quarantined by the gateway if it fails."""
    item = job.rebuild(document_id)
    try:
        result: LLMResult[Any] = gateway.call(
            stage=job.stage, model=job.model, prompt_version=job.prompt_version,
            system=job.system, user=item.user, output_model=job.output_model,
            provenance=item.provenance, max_tokens=job.max_tokens * 2, effort=job.effort,
            attempts=1, prior_attempts=1,
        )  # fmt: skip
    except BudgetPausedError:
        job.requeue(document_id)
        counts["requeued"] += 1
        return
    if result.ok and result.parsed is not None:
        job.store(document_id, result.parsed, (result.input_tokens, result.output_tokens))
        counts["retried_ok"] += 1
    else:
        job.fail(document_id)
        counts["quarantined"] += 1


def collect(gateway: Gateway, jobs: dict[str, BatchJob[Any]]) -> dict[str, int]:
    """Process every submitted batch that has ended. ``jobs`` maps stage -> BatchJob."""
    counts = {"batches": 0, "ok": 0, "retried_ok": 0, "quarantined": 0, "requeued": 0,
              "pending": 0}  # fmt: skip
    with session_factory()() as session:
        open_batches = list(session.scalars(select(LLMBatch).where(LLMBatch.status == "submitted")))
        session.expunge_all()
    for batch in open_batches:
        job = jobs.get(batch.stage)
        if job is None:
            continue
        remote = gateway.client.messages.batches.retrieve(batch.anthropic_batch_id)
        if remote.processing_status != "ended":
            counts["pending"] += 1
            continue
        if batch.prompt_version != job.prompt_version:
            # The prompt changed while the batch ran: its results would be stored under the
            # wrong version, so the documents go back to the queue instead.
            for document_id in batch.items.values():
                job.requeue(int(document_id))
            counts["requeued"] += len(batch.items)
            _close(batch.id, remote)
            continue
        seen: set[str] = set()
        for entry in gateway.client.messages.batches.results(batch.anthropic_batch_id):
            document_id = batch.items.get(entry.custom_id)
            if document_id is None:
                continue
            seen.add(entry.custom_id)
            _handle(gateway, job, entry, int(document_id), counts)
        for custom_id, document_id in batch.items.items():  # results missing entirely
            if custom_id not in seen:
                _retry(gateway, job, int(document_id), counts)
        _close(batch.id, remote)
        counts["batches"] += 1
    if counts["batches"] or counts["pending"]:
        log.info("batch collection: %s", counts)
    return counts


def _close(batch_id: int, remote: Any) -> None:
    with session_factory()() as session, session.begin():
        row = session.get_one(LLMBatch, batch_id)
        row.status = "collected"
        row.collected_at = dt.datetime.now(dt.UTC)
        row.result_counts = _request_counts(remote)


def _request_counts(remote: Any) -> dict[str, int]:
    rc = getattr(remote, "request_counts", None)
    fields = ("processing", "succeeded", "errored", "canceled", "expired")
    return {f: int(getattr(rc, f, 0) or 0) for f in fields} if rc is not None else {}


def _handle(
    gateway: Gateway, job: BatchJob[Any], entry: Any, document_id: int, counts: dict[str, int]
) -> None:
    result = entry.result
    if result.type != "succeeded":  # errored | canceled | expired: no output to judge
        _retry(gateway, job, document_id, counts)
        return
    msg = result.message
    checked = assess(msg, job.output_model)
    with session_factory()() as session, session.begin():
        gateway.record(
            session, stage=job.stage, model=job.model, prompt_version=job.prompt_version,
            resp=msg, status=checked.status, batch=True,
        )  # fmt: skip
    if checked.parsed is not None:
        tokens = (msg.usage.input_tokens or 0, msg.usage.output_tokens or 0)
        job.store(document_id, checked.parsed, tokens)
        counts["ok"] += 1
    elif checked.status == "refusal":  # a refusal will not change on retry
        with session_factory()() as session, session.begin():
            gateway.quarantine(
                session, stage=job.stage, model=job.model, prompt_version=job.prompt_version,
                prov=job.rebuild(document_id).provenance, reason="refusal",
                error=checked.error, raw=checked.raw, attempts=1,
            )  # fmt: skip
        job.fail(document_id)
        counts["quarantined"] += 1
    else:
        _retry(gateway, job, document_id, counts)
