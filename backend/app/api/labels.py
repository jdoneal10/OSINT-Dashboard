"""Owner hand labels for the extraction precision evaluation (Phase 2 Step 6, ADR 0004).

A label judges one pipeline output: a whole record (``field = ""``) or one field of it.

- ``events`` / ``seizures``: was the extracted record correct, partly wrong (name the field),
  or wrong?
- ``documents`` with ``field = "relevant"``: was the pipeline's relevance decision
  (extracted vs filtered out) correct? Used for filter recall.

``prompt_version`` is copied from the judged record so results stay tied to the prompt that
produced them after re-extraction.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.documents import LabelOut, label_out
from app.db.models import (
    Document,
    Event,
    Label,
    Seizure,
    Source,
    event_documents,
    seizure_documents,
)
from app.db.session import get_session

router = APIRouter(prefix="/labels", tags=["labels"])
DB = Annotated[Session, Depends(get_session)]

QUEUE_STATUSES = ("extracted", "filtered_out")


class LabelIn(BaseModel):
    document_id: int
    target_table: Literal["events", "seizures", "documents"]
    target_id: int
    field: str = Field(default="", max_length=64)
    verdict: Literal["correct", "incorrect", "partial"]
    note: str | None = Field(default=None, max_length=2000)


def _judged(session: Session, body: LabelIn) -> tuple[str | None, str | None]:
    """Validate the target belongs to the document.

    Returns (prompt version judged, relevance decision judged); the decision is set only for
    document relevance labels and is frozen with the label.
    """
    if body.target_table == "documents":
        doc = session.get(Document, body.target_id)
        if doc is None or doc.id != body.document_id:
            raise HTTPException(422, "target document does not match document_id")
        decision = "relevant" if doc.pipeline_status == "extracted" else "not_relevant"
        return doc.prompt_version or doc.relevance_model, decision
    model: type[Event] | type[Seizure]
    if body.target_table == "events":
        model, link, col = Event, event_documents, event_documents.c.event_id
    else:
        model, link, col = Seizure, seizure_documents, seizure_documents.c.seizure_id
    linked = session.scalar(
        select(func.count()).where(col == body.target_id, link.c.document_id == body.document_id)
    )
    if not linked:
        raise HTTPException(422, f"{body.target_table} {body.target_id} is not from this document")
    version: str | None = session.scalar(
        select(model.prompt_version).where(model.id == body.target_id)
    )
    return version, None


@router.get("", response_model=list[LabelOut])
def list_labels(session: DB, document_id: int | None = None) -> list[LabelOut]:
    stmt = select(Label).order_by(Label.document_id, Label.id)
    if document_id is not None:
        stmt = stmt.where(Label.document_id == document_id)
    return [label_out(lab) for lab in session.scalars(stmt)]


@router.put("", response_model=LabelOut)
def put_label(body: LabelIn, session: DB) -> LabelOut:
    """Create or replace the label for (target_table, target_id, field)."""
    version, decision = _judged(session, body)
    values = body.model_dump() | {"prompt_version": version, "judged_decision": decision}
    ins = insert(Label).values(**values)
    stmt = ins.on_conflict_do_update(
        constraint="uq_labels_target",
        set_={
            "verdict": ins.excluded.verdict,
            "note": ins.excluded.note,
            "prompt_version": ins.excluded.prompt_version,
            "judged_decision": ins.excluded.judged_decision,
            "document_id": ins.excluded.document_id,
            "updated_at": func.now(),
        },
    ).returning(Label.id)
    label_id = session.scalar(stmt)
    session.commit()
    return label_out(session.get_one(Label, label_id))


@router.delete("/{label_id}", status_code=204)
def delete_label(label_id: int, session: DB) -> Response:
    lab = session.get(Label, label_id)
    if lab is None:
        raise HTTPException(404, "label not found")
    session.delete(lab)
    session.commit()
    return Response(status_code=204)


class QueueItem(BaseModel):
    document_id: int
    source: str
    status: str
    title: str | None
    n_records: int
    n_labeled_records: int
    relevance_labeled: bool
    done: bool


class LabelQueue(BaseModel):
    size: int
    done: int
    items: list[QueueItem]


def _stable_rank(doc_id: int) -> str:
    return hashlib.sha256(f"label-sample:{doc_id}".encode()).hexdigest()


@router.get("/queue", response_model=LabelQueue)
def label_queue(
    session: DB,
    size: Annotated[int, Query(ge=1, le=500)] = 100,
    filtered_share: Annotated[
        float, Query(ge=0, le=1, description="share of filtered-out documents (filter recall)")
    ] = 0.2,
) -> LabelQueue:
    """Deterministic stratified sample: round-robin across sources within each status.

    The same documents come back on every call (stable hash order), so progress persists;
    new documents only enter while the sample is not yet full.
    """
    rows = session.execute(
        select(Document.id, Source.slug, Document.pipeline_status, Document.title)
        .join(Source, Source.id == Document.source_id)
        .where(
            Document.pipeline_status.in_(QUEUE_STATUSES),
            Document.duplicate_of_id.is_(None),
            Document.relevance_score.is_not(None),
        )
    ).all()
    quota = {"filtered_out": round(size * filtered_share)}
    quota["extracted"] = size - quota["filtered_out"]
    picked: list[tuple[int, str, str, str | None]] = []
    for status in QUEUE_STATUSES:
        strata: dict[str, list[tuple[int, str, str, str | None]]] = defaultdict(list)
        for r in sorted((r for r in rows if r[2] == status), key=lambda r: _stable_rank(r[0])):
            strata[r[1]].append(tuple(r))  # type: ignore[arg-type]
        queues = [strata[k] for k in sorted(strata)]
        taken = 0
        while taken < quota[status] and any(queues):
            for q in queues:
                if q and taken < quota[status]:
                    picked.append(q.pop(0))
                    taken += 1
    ids = [p[0] for p in picked]
    records: dict[int, set[tuple[str, int]]] = defaultdict(set)
    for doc_id, ev_id in session.execute(
        select(event_documents.c.document_id, event_documents.c.event_id).where(
            event_documents.c.document_id.in_(ids)
        )
    ):
        records[doc_id].add(("events", ev_id))
    for doc_id, sz_id in session.execute(
        select(seizure_documents.c.document_id, seizure_documents.c.seizure_id).where(
            seizure_documents.c.document_id.in_(ids)
        )
    ):
        records[doc_id].add(("seizures", sz_id))
    labeled: dict[int, set[tuple[str, int]]] = defaultdict(set)
    relevance: set[int] = set()
    for doc_id, table, target in session.execute(
        select(Label.document_id, Label.target_table, Label.target_id).where(
            Label.document_id.in_(ids)
        )
    ):
        if table == "documents":
            relevance.add(doc_id)
        else:
            labeled[doc_id].add((table, target))
    items = []
    for doc_id, slug, status, title in picked:
        n_labeled = len(records[doc_id] & labeled[doc_id])
        items.append(
            QueueItem(
                document_id=doc_id,
                source=slug,
                status=status,
                title=title,
                n_records=len(records[doc_id]),
                n_labeled_records=n_labeled,
                relevance_labeled=doc_id in relevance,
                done=doc_id in relevance and n_labeled == len(records[doc_id]),
            )
        )
    return LabelQueue(size=len(items), done=sum(i.done for i in items), items=items)
