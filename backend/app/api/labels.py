"""Owner hand labels for the extraction precision evaluation (Phase 2 Step 6, ADR 0004).

A label judges one pipeline output: a whole record (``field = ""``) or one field of it.

- ``events`` / ``seizures``: was the extracted record correct, partly wrong (name the field),
  or wrong?
- ``documents`` with ``field = "relevant"``: was the pipeline's relevance decision
  (extracted vs filtered out) correct? Used for filter recall.
- ``persons`` (ADR 0013): the person as extracted from this document. ``field`` names wrong
  attributes and any safeguard violation (an excluded category such as a victim or minor,
  a contact detail, a missed U.S. nexus, an unsupported claim). One label per document.

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
    PersonAttribute,
    Seizure,
    Source,
    event_documents,
    seizure_documents,
)
from app.db.session import get_session
from app.enrich.extract import LABELED_VERSION as EXTRACT_VERSION

router = APIRouter(prefix="/labels", tags=["labels"])
DB = Annotated[Session, Depends(get_session)]

QUEUE_STATUSES = ("extracted", "filtered_out")
RECORD_TABLES = ("events", "seizures")


class LabelIn(BaseModel):
    document_id: int
    target_table: Literal["events", "seizures", "documents", "persons"]
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
    if body.target_table == "persons":
        person_version = session.scalar(
            select(PersonAttribute.prompt_version)
            .where(
                PersonAttribute.person_id == body.target_id,
                PersonAttribute.document_id == body.document_id,
            )
            .limit(1)
        )
        if person_version is None:
            raise HTTPException(422, f"person {body.target_id} is not from this document")
        return person_version, None
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
    top_up: bool = False


class LabelQueue(BaseModel):
    size: int
    done: int
    items: list[QueueItem]


def _stable_rank(doc_id: int) -> str:
    return hashlib.sha256(f"label-sample:{doc_id}".encode()).hexdigest()


Row = tuple[int, str, str, str | None]


def _round_robin(rows: list[Row]) -> list[list[Row]]:
    """Per-source queues in stable hash order, sources sorted by slug."""
    strata: dict[str, list[Row]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: _stable_rank(r[0])):
        strata[r[1]].append(r)
    return [strata[k] for k in sorted(strata)]


def _record_top_up(session: Session, rows: list[Row], picked: list[Row], target: int) -> list[Row]:
    """Extracted documents with current-prompt records, appended after the base sample until
    ``target`` documents with records are labeled or queued (the evaluation's sample gate).

    Documents already labeled count toward the target, so labeling a top-up item never
    changes which items are shown.
    """
    current: set[int] = set()
    for model, link, col in (
        (Event, event_documents, event_documents.c.event_id),
        (Seizure, seizure_documents, seizure_documents.c.seizure_id),
    ):
        current.update(
            session.scalars(
                select(link.c.document_id)
                .join(model, model.id == col)
                .where(model.prompt_version == EXTRACT_VERSION)
            )
        )
    covered = set(
        session.scalars(
            select(Label.document_id).where(
                Label.target_table.in_(RECORD_TABLES), Label.prompt_version == EXTRACT_VERSION
            )
        )
    )
    in_sample = {p[0] for p in picked}
    covered |= in_sample & current
    queues = _round_robin(
        [r for r in rows if r[2] == "extracted" and r[0] in current and r[0] not in in_sample]
    )
    extra: list[Row] = []
    while len(covered) < target and any(queues):
        for q in queues:
            if q and len(covered) < target:
                r = q.pop(0)
                extra.append(r)
                covered.add(r[0])
    return extra


def _records_for(session: Session, ids: list[int]) -> dict[int, set[tuple[str, int]]]:
    """Records to label per document: its events, seizures and persons (ADR 0013)."""
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
    for doc_id, person_id in session.execute(
        select(PersonAttribute.document_id, PersonAttribute.person_id)
        .where(PersonAttribute.document_id.in_(ids))
        .distinct()
    ):
        if doc_id is not None:
            records[doc_id].add(("persons", person_id))
    return records


@router.get("/queue", response_model=LabelQueue)
def label_queue(
    session: DB,
    size: Annotated[int, Query(ge=1, le=500)] = 100,
    filtered_share: Annotated[
        float, Query(ge=0, le=1, description="share of filtered-out documents (filter recall)")
    ] = 0.2,
    record_documents: Annotated[
        int, Query(ge=0, le=500, description="top up until this many documents have records")
    ] = 0,
) -> LabelQueue:
    """Deterministic stratified sample: round-robin across sources within each status.

    The same documents come back on every call (stable hash order), so progress persists;
    new documents only enter while the sample is not yet full. With ``record_documents``,
    documents that have extracted records are appended (``top_up``) until that many documents
    with records are labeled or queued, because documents with no records add nothing to
    record precision.
    """
    rows: list[Row] = [
        (r[0], r[1], r[2], r[3])
        for r in session.execute(
            select(Document.id, Source.slug, Document.pipeline_status, Document.title)
            .join(Source, Source.id == Document.source_id)
            .where(
                Document.pipeline_status.in_(QUEUE_STATUSES),
                Document.duplicate_of_id.is_(None),
                Document.relevance_score.is_not(None),
            )
        )
    ]
    quota = {"filtered_out": round(size * filtered_share)}
    quota["extracted"] = size - quota["filtered_out"]
    picked: list[Row] = []
    for status in QUEUE_STATUSES:
        queues = _round_robin([r for r in rows if r[2] == status])
        taken = 0
        while taken < quota[status] and any(queues):
            for q in queues:
                if q and taken < quota[status]:
                    picked.append(q.pop(0))
                    taken += 1
    n_base = len(picked)
    if record_documents:
        picked += _record_top_up(session, rows, picked, record_documents)
    ids = [p[0] for p in picked]
    records = _records_for(session, ids)
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
    for n, (doc_id, slug, status, title) in enumerate(picked):
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
                top_up=n >= n_base,
            )
        )
    return LabelQueue(size=len(items), done=sum(i.done for i in items), items=items)
