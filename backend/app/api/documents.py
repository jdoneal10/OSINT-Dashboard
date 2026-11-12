"""News feed and document detail (Phase 2 unstructured layer, ADR 0004).

Documents are public articles and releases; ACLED never appears here (ADR 0003). The feed
hides documents whose derived records all fall outside the AOI unless
``include_out_of_aoi=true``.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2 import Geometry
from pydantic import BaseModel
from sqlalchemy import Select, cast, exists, func, not_, or_, select, tuple_
from sqlalchemy.orm import Session

from app.api.events import EventOut, actors_for, documents_for, event_out, event_select
from app.db.models import (
    PIPELINE_STATUSES,
    Document,
    Event,
    EventCluster,
    Label,
    LLMQuarantine,
    Seizure,
    Source,
    actor_events,
    event_documents,
    seizure_documents,
)
from app.db.session import get_session

router = APIRouter(prefix="/documents", tags=["documents"])
DB = Annotated[Session, Depends(get_session)]
MAX_PAGE = 200


# --------------------------------------------------------------------------- shapes


class SourceRef(BaseModel):
    slug: str
    name: str
    reliability: str


class ClusterRef(BaseModel):
    id: int
    reliability: str | None
    credibility: int | None
    admiralty: str | None  # e.g. "B2"
    n_documents: int
    n_independent_sources: int
    has_conflicts: bool


class DocumentSummary(BaseModel):
    id: int
    title: str | None
    summary_en: str | None
    source: SourceRef
    url: str | None
    published_at: dt.datetime | None
    retrieved_at: dt.datetime
    language: str | None
    status: str
    relevance_score: float | None
    duplicate_of_id: int | None
    n_events: int
    n_seizures: int
    in_aoi: bool  # false when every derived record lies outside the AOI
    clusters: list[ClusterRef]
    admiralty: str | None  # best grade among its clusters


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    next_cursor: str | None


class SeizureOut(BaseModel):
    id: int
    source: str
    seizure_date: dt.date
    substance: str
    chemical_class: str | None
    quantity: float | None
    unit: str | None
    seizing_agency: str | None
    admin1_code: str | None
    node_id: int | None
    lon: float | None
    lat: float | None
    in_aoi: bool
    confidence: float | None
    credibility: int | None
    llm_model: str | None
    prompt_version: str | None


class QuarantineOut(BaseModel):
    id: int
    stage: str
    model: str
    prompt_version: str
    reason: str
    error: str | None
    created_at: dt.datetime


class LabelOut(BaseModel):
    id: int
    document_id: int
    target_table: str
    target_id: int
    field: str
    verdict: str
    note: str | None
    prompt_version: str | None
    updated_at: dt.datetime


class DocumentDetail(DocumentSummary):
    original_text: str | None
    feed_summary: str | None  # publisher teaser, when the feed supplied one
    text_policy: str
    relevance_model: str | None
    llm_model: str | None
    prompt_version: str | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
    events: list[EventOut]
    seizures: list[SeizureOut]
    quarantine: list[QuarantineOut]
    labels: list[LabelOut]
    duplicates: list[int]  # documents marked as copies of this one


# --------------------------------------------------------------------------- helpers


def admiralty(reliability: str | None, credibility: int | None) -> str | None:
    if reliability is None or credibility is None:
        return None
    return f"{reliability}{credibility}"


def _sort_ts() -> Any:
    return func.coalesce(Document.published_at, Document.retrieved_at)


def _has_record(in_aoi: bool | None) -> Any:
    ev = select(event_documents.c.event_id).join(Event, Event.id == event_documents.c.event_id)
    sz = select(seizure_documents.c.seizure_id).join(
        Seizure, Seizure.id == seizure_documents.c.seizure_id
    )
    ev = ev.where(event_documents.c.document_id == Document.id)
    sz = sz.where(seizure_documents.c.document_id == Document.id)
    if in_aoi is not None:
        ev = ev.where(Event.in_aoi.is_(in_aoi))
        sz = sz.where(Seizure.in_aoi.is_(in_aoi))
    return or_(exists(ev), exists(sz))


def in_aoi_clause() -> Any:
    """Document has no derived records, or at least one inside the AOI."""
    return or_(not_(_has_record(None)), _has_record(True))


def _clusters_for(session: Session, doc_ids: list[int]) -> dict[int, list[ClusterRef]]:
    out: dict[int, list[ClusterRef]] = {}
    if not doc_ids:
        return out
    rows = session.execute(
        select(event_documents.c.document_id, EventCluster)
        .join(Event, Event.id == event_documents.c.event_id)
        .join(EventCluster, EventCluster.id == Event.cluster_id)
        .where(event_documents.c.document_id.in_(doc_ids))
        .distinct()
        .order_by(event_documents.c.document_id, EventCluster.id)
    ).all()
    for doc_id, c in rows:
        out.setdefault(doc_id, []).append(cluster_ref(c))
    return out


def cluster_ref(c: EventCluster) -> ClusterRef:
    return ClusterRef(
        id=c.id,
        reliability=c.reliability,
        credibility=c.credibility,
        admiralty=admiralty(c.reliability, c.credibility),
        n_documents=c.n_documents,
        n_independent_sources=c.n_independent_sources,
        has_conflicts=bool(c.conflicts),
    )


def _best(clusters: list[ClusterRef]) -> str | None:
    graded = [c for c in clusters if c.admiralty]
    if not graded:
        return None
    best = min(graded, key=lambda c: (c.credibility or 9, c.reliability or "Z"))
    return best.admiralty


def summary_select() -> Select[Any]:
    n_events = (
        select(func.count())
        .where(event_documents.c.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    n_seizures = (
        select(func.count())
        .where(seizure_documents.c.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    return select(Document, Source, n_events, n_seizures, in_aoi_clause()).join(
        Source, Source.id == Document.source_id
    )


def summaries(session: Session, rows: list[Any]) -> list[DocumentSummary]:
    clusters = _clusters_for(session, [r[0].id for r in rows])
    return [_summary(r, clusters.get(r[0].id, [])) for r in rows]


def _summary(row: Any, clusters: list[ClusterRef]) -> DocumentSummary:
    doc, src, n_events, n_seizures, inside = row
    return DocumentSummary(
        id=doc.id,
        title=doc.title,
        summary_en=doc.translated_text,
        source=SourceRef(slug=src.slug, name=src.name, reliability=src.reliability),
        url=doc.source_url,
        published_at=doc.published_at,
        retrieved_at=doc.retrieved_at,
        language=doc.language,
        status=doc.pipeline_status,
        relevance_score=float(doc.relevance_score) if doc.relevance_score is not None else None,
        duplicate_of_id=doc.duplicate_of_id,
        n_events=n_events,
        n_seizures=n_seizures,
        in_aoi=bool(inside),
        clusters=clusters,
        admiralty=_best(clusters),
    )


def seizures_for(session: Session, doc_id: int) -> list[SeizureOut]:
    point = cast(Seizure.geom, Geometry)
    rows = session.execute(
        select(Seizure, Source.slug, func.ST_X(point), func.ST_Y(point))
        .join(Source, Source.id == Seizure.source_id)
        .join(seizure_documents, seizure_documents.c.seizure_id == Seizure.id)
        .where(seizure_documents.c.document_id == doc_id)
        .order_by(Seizure.id)
    ).all()
    return [
        SeizureOut(
            id=s.id,
            source=slug,
            seizure_date=s.seizure_date,
            substance=s.substance,
            chemical_class=s.chemical_class,
            quantity=float(s.quantity) if s.quantity is not None else None,
            unit=s.unit,
            seizing_agency=s.seizing_agency,
            admin1_code=s.admin1_code,
            node_id=s.node_id,
            lon=x,
            lat=y,
            in_aoi=s.in_aoi,
            confidence=float(s.confidence) if s.confidence is not None else None,
            credibility=s.credibility,
            llm_model=s.llm_model,
            prompt_version=s.prompt_version,
        )
        for s, slug, x, y in rows
    ]


def label_out(lab: Label) -> LabelOut:
    return LabelOut(
        id=lab.id,
        document_id=lab.document_id,
        target_table=lab.target_table,
        target_id=lab.target_id,
        field=lab.field,
        verdict=lab.verdict,
        note=lab.note,
        prompt_version=lab.prompt_version,
        updated_at=lab.updated_at,
    )


def _docs_with_events(
    admin1: list[str] | None, event_type: list[str] | None, actor: list[int] | None
) -> Select[Any]:
    ev = select(event_documents.c.document_id).join(Event, Event.id == event_documents.c.event_id)
    if admin1:
        ev = ev.where(Event.admin1_code.in_(admin1))
    if event_type:
        ev = ev.where(Event.event_type.in_(event_type))
    if actor:
        ev = ev.where(
            Event.id.in_(select(actor_events.c.event_id).where(actor_events.c.actor_id.in_(actor)))
        )
    return ev


# --------------------------------------------------------------------------- routes


@router.get("", response_model=DocumentPage)
def list_documents(
    session: DB,
    start: dt.date | None = None,
    end: dt.date | None = None,
    source: Annotated[list[str] | None, Query(description="source slugs")] = None,
    status: Annotated[
        list[str] | None,
        Query(description=f"pipeline status; default extracted. {PIPELINE_STATUSES}"),
    ] = None,
    admin1: Annotated[list[str] | None, Query(description="documents with events here")] = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    actor: Annotated[list[int] | None, Query(description="documents with events linked")] = None,
    q: Annotated[str | None, Query(description="search title and English summary")] = None,
    include_duplicates: bool = False,
    include_out_of_aoi: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: Annotated[str | None, Query(description="opaque; from next_cursor")] = None,
) -> DocumentPage:
    """News feed, newest first. Each item carries its clusters and best Admiralty grade."""
    stmt = summary_select().where(Document.pipeline_status.in_(status or ["extracted"]))
    if start:
        stmt = stmt.where(_sort_ts() >= dt.datetime.combine(start, dt.time.min, dt.UTC))
    if end:
        stmt = stmt.where(
            _sort_ts() < dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, dt.UTC)
        )
    if source:
        stmt = stmt.where(Source.slug.in_(source))
    if not include_duplicates:
        stmt = stmt.where(Document.duplicate_of_id.is_(None))
    if not include_out_of_aoi:
        stmt = stmt.where(in_aoi_clause())
    if admin1 or event_type or actor:
        stmt = stmt.where(Document.id.in_(_docs_with_events(admin1, event_type, actor)))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.translated_text.ilike(like)))
    if cursor:
        try:
            ts_s, id_s = cursor.rsplit("_", 1)
            key = (dt.datetime.fromisoformat(ts_s), int(id_s))
        except ValueError as exc:
            raise HTTPException(422, "invalid cursor") from exc
        stmt = stmt.where(tuple_(_sort_ts(), Document.id) < tuple_(*key))
    rows = session.execute(
        stmt.order_by(_sort_ts().desc(), Document.id.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    nxt = None
    if len(rows) > limit:
        last = page[-1][0]
        nxt = f"{(last.published_at or last.retrieved_at).isoformat()}_{last.id}"
    return DocumentPage(items=summaries(session, list(page)), next_cursor=nxt)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: int, session: DB) -> DocumentDetail:
    row = session.execute(summary_select().where(Document.id == document_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "document not found")
    doc: Document = row[0]
    summary = summaries(session, [row])[0]
    ev_rows = session.execute(
        event_select()
        .join(event_documents, event_documents.c.event_id == Event.id)
        .where(event_documents.c.document_id == document_id)
        .order_by(Event.id)
    ).all()
    ids = [r[0].id for r in ev_rows]
    actors, docs = actors_for(session, ids), documents_for(session, ids)
    quarantine = session.scalars(
        select(LLMQuarantine)
        .where(LLMQuarantine.document_id == document_id)
        .order_by(LLMQuarantine.id)
    ).all()
    labels = session.scalars(
        select(Label).where(Label.document_id == document_id).order_by(Label.id)
    ).all()
    duplicates = session.scalars(
        select(Document.id).where(Document.duplicate_of_id == document_id).order_by(Document.id)
    ).all()
    return DocumentDetail(
        **summary.model_dump(),
        original_text=doc.original_text,
        feed_summary=doc.summary,
        text_policy=doc.text_policy,
        relevance_model=doc.relevance_model,
        llm_model=doc.llm_model,
        prompt_version=doc.prompt_version,
        llm_input_tokens=doc.llm_input_tokens,
        llm_output_tokens=doc.llm_output_tokens,
        events=[event_out(r, actors, docs) for r in ev_rows],
        seizures=seizures_for(session, document_id),
        quarantine=[
            QuarantineOut(
                id=x.id,
                stage=x.stage,
                model=x.model,
                prompt_version=x.prompt_version,
                reason=x.reason,
                error=x.error,
                created_at=x.created_at,
            )
            for x in quarantine
        ],
        labels=[label_out(lab) for lab in labels],
        duplicates=list(duplicates),
    )
