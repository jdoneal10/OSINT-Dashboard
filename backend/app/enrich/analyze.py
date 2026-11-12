"""Sonnet analytic layer: corroboration judgments for clusters with conflicting reports.

Only clusters whose member reports disagree (fatalities, municipality, event type) are
escalated, newest first, capped per run. Inputs are the cluster's document-derived events and
their documents' English summaries, declared as provenance so the gateway's ACLED guard
applies (ACLED events are never clustered or sent; ADR 0003).

Output uses ICD 203 estimative language. Every judgment must cite document ids that were
actually provided; an assessment citing anything else is quarantined, not stored.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ClusterAssessment,
    Document,
    Event,
    EventCluster,
    LLMQuarantine,
    Source,
    event_documents,
)
from app.db.session import session_factory
from app.enrich.llm.client import BudgetPausedError, Gateway, Provenance
from app.enrich.llm.pricing import SONNET

log = logging.getLogger(__name__)

PROMPT_VERSION = "analyze-v1"
ICD203 = Literal[
    "almost no chance",
    "very unlikely",
    "unlikely",
    "roughly even chance",
    "likely",
    "very likely",
    "almost certain",
]

SYSTEM = """You are an all-source analyst writing short corroboration judgments for an \
UNCLASSIFIED open-source dashboard on transnational criminal organizations in Mexico, \
Central America and the U.S. border. You receive several reports that appear to describe the \
same incident but disagree on some details.

Write in ICD 203 style:
- Use estimative language ("we assess", "likely", "almost certain") and pick the matching \
likelihood term exactly from: almost no chance, very unlikely, unlikely, roughly even chance, \
likely, very likely, almost certain.
- State analytic confidence (low, moderate, high) separately from likelihood, based on \
source quality, independence and corroboration.
- Distinguish what the reports say from your judgment. Note when sources are official \
claims, and when apparent agreement could come from one shared origin.
- Cite the document ids that support each judgment, using only ids given in the input.
- Never name individual people; refer to roles.
- Keep "judgment" under 120 words."""


class Resolved(BaseModel):
    fatalities: int | None = Field(ge=0, description="Best-supported count, or null")
    municipality: str | None = Field(description="Best-supported municipality, or null")
    event_type: str | None


class AssessmentOut(BaseModel):
    same_incident: bool = Field(description="Do the reports describe one incident?")
    judgment: str
    likelihood: ICD203
    analytic_confidence: Literal["low", "moderate", "high"]
    resolved: Resolved
    cited_document_ids: list[int] = Field(min_length=1)


def build_input(session: Session, cluster: EventCluster) -> tuple[str, list[int], list[int]]:
    events = list(
        session.scalars(select(Event).where(Event.cluster_id == cluster.id).order_by(Event.id))
    )
    lines = [f"CLUSTER {cluster.id}: conflicting fields {sorted(cluster.conflicts)}", ""]
    doc_ids: list[int] = []
    for ev in events:
        docs = session.execute(
            select(Document, Source.name, Source.reliability)
            .join(event_documents, event_documents.c.document_id == Document.id)
            .join(Source, Source.id == Document.source_id)
            .where(event_documents.c.event_id == ev.id)
        ).all()
        for doc, src_name, grade in docs:
            if doc.id not in doc_ids:
                doc_ids.append(doc.id)
            lines.append(
                f"[document {doc.id}] {src_name} (reliability {grade}), published "
                f"{doc.published_at.date() if doc.published_at else 'unknown'}\n"
                f"  reported: type={ev.event_type}; date={ev.event_date}; "
                f"fatalities={ev.fatalities}; place={ev.location_name}, {ev.admin2_name}, "
                f"{ev.admin1_name}\n  summary: {doc.translated_text or doc.title or ''}"
            )
    return "\n".join(lines), doc_ids, [e.id for e in events]


def needs_analysis(session: Session, limit: int) -> list[int]:
    assessed = select(ClusterAssessment.cluster_id).where(
        ClusterAssessment.prompt_version == PROMPT_VERSION
    )
    return list(
        session.scalars(
            select(EventCluster.id)
            .where(EventCluster.conflicts != {}, EventCluster.id.not_in(assessed))
            .order_by(EventCluster.last_date.desc())
            .limit(limit)
        )
    )


def run_analyze(limit: int = 20, gateway: Gateway | None = None) -> dict[str, int]:
    gateway = gateway or Gateway()
    counts = {"assessed": 0, "quarantined": 0}
    with session_factory()() as session:
        ids = needs_analysis(session, limit)
    for cid in ids:
        with session_factory()() as session:
            cluster = session.get_one(EventCluster, cid)
            user, doc_ids, event_ids = build_input(session, cluster)
        if not doc_ids:
            continue
        try:
            result = gateway.call(
                stage="analyze",
                model=SONNET,
                prompt_version=PROMPT_VERSION,
                system=SYSTEM,
                user=user,
                output_model=AssessmentOut,
                provenance=Provenance(
                    document_ids=tuple(doc_ids), event_ids=tuple(event_ids), cluster_id=cid
                ),
                max_tokens=4000,
                effort="medium",
            )
        except BudgetPausedError:
            log.warning("budget paused; stopping analysis")
            break
        with session_factory()() as session, session.begin():
            out = result.parsed
            bad_cites = sorted(set(out.cited_document_ids) - set(doc_ids)) if out else []
            if not result.ok or out is None or bad_cites:
                if out is not None and bad_cites:
                    session.add(
                        LLMQuarantine(
                            stage="analyze",
                            cluster_id=cid,
                            document_id=doc_ids[0],
                            model=SONNET,
                            prompt_version=PROMPT_VERSION,
                            reason="validation",
                            error=f"cited ids not in input: {bad_cites}",
                            raw_output=out.model_dump_json(),
                        )
                    )
                counts["quarantined"] += 1
                continue
            session.add(
                ClusterAssessment(
                    cluster_id=cid,
                    judgment=out.judgment,
                    likelihood=out.likelihood,
                    analytic_confidence=out.analytic_confidence,
                    resolved=out.resolved.model_dump() | {"same_incident": out.same_incident},
                    cited_document_ids=out.cited_document_ids,
                    cited_event_ids=event_ids,
                    llm_model=SONNET,
                    prompt_version=PROMPT_VERSION,
                    llm_input_tokens=result.input_tokens,
                    llm_output_tokens=result.output_tokens,
                )
            )
            counts["assessed"] += 1
    log.info("analysis: %s", counts)
    return counts
