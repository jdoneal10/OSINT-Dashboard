"""Corroboration clusters: member events and documents, Admiralty grade, Sonnet assessment."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2 import Geometry
from pydantic import BaseModel
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.api.documents import (
    ClusterRef,
    DocumentSummary,
    cluster_ref,
    clusters_with_acled,
    summaries,
    summary_select,
)
from app.api.events import EventOut, actors_for, documents_for, event_out, event_select
from app.db.models import ClusterAssessment, Document, Event, EventCluster, event_documents
from app.db.session import get_session

router = APIRouter(prefix="/clusters", tags=["clusters"])
DB = Annotated[Session, Depends(get_session)]


class AssessmentOut(BaseModel):
    id: int
    judgment: str
    likelihood: str | None
    analytic_confidence: str | None
    resolved: dict[str, Any]
    cited_document_ids: list[int]
    cited_event_ids: list[int]
    llm_model: str | None
    prompt_version: str | None
    created_at: dt.datetime


class ClusterDetail(ClusterRef):
    first_date: dt.date
    last_date: dt.date
    event_type: str
    admin1_code: str | None
    lon: float | None
    lat: float | None
    n_events: int
    confidence: float | None
    conflicts: dict[str, Any]
    events: list[EventOut]
    documents: list[DocumentSummary]
    assessments: list[AssessmentOut]


@router.get("/{cluster_id}", response_model=ClusterDetail)
def get_cluster(cluster_id: int, session: DB) -> ClusterDetail:
    point = cast(EventCluster.centroid, Geometry)
    row = session.execute(
        select(EventCluster, func.ST_X(point), func.ST_Y(point)).where(
            EventCluster.id == cluster_id
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "cluster not found")
    c, lon, lat = row
    ev_rows = session.execute(
        event_select().where(Event.cluster_id == cluster_id).order_by(Event.event_date, Event.id)
    ).all()
    ids = [r[0].id for r in ev_rows]
    actors, docs = actors_for(session, ids), documents_for(session, ids)
    doc_rows = session.execute(
        summary_select()
        .where(
            Document.id.in_(
                select(event_documents.c.document_id).where(event_documents.c.event_id.in_(ids))
            )
        )
        .order_by(Document.id)
    ).all()
    assessments = session.scalars(
        select(ClusterAssessment)
        .where(ClusterAssessment.cluster_id == cluster_id)
        .order_by(ClusterAssessment.id.desc())
    ).all()
    return ClusterDetail(
        **cluster_ref(c, bool(clusters_with_acled(session, [c.id]))).model_dump(),
        first_date=c.first_date,
        last_date=c.last_date,
        event_type=c.event_type,
        admin1_code=c.admin1_code,
        lon=lon,
        lat=lat,
        n_events=c.n_events,
        confidence=float(c.confidence) if c.confidence is not None else None,
        conflicts=c.conflicts,
        events=[event_out(r, actors, docs) for r in ev_rows],
        documents=summaries(session, list(doc_rows)),
        assessments=[
            AssessmentOut(
                id=a.id,
                judgment=a.judgment,
                likelihood=a.likelihood,
                analytic_confidence=a.analytic_confidence,
                resolved=a.resolved,
                cited_document_ids=a.cited_document_ids,
                cited_event_ids=a.cited_event_ids,
                llm_model=a.llm_model,
                prompt_version=a.prompt_version,
                created_at=a.created_at,
            )
            for a in assessments
        ],
    )
