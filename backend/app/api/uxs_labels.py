"""Owner labels on UxS verdicts (ADR 0009 amendment 1): the review list and label writes.

A UxS label judges one event's UxS fields (activity, platform, missions, payloads), whether
they came from the ACLED UxS pass or from news extraction. Only events with UxS fields are
reviewed: the labels measure precision, not recall.

The review list is a deterministic sample: events are grouped by stratum (the activity),
each group in stable hash order, and the groups are interleaved, so labeling from the top
covers seizures, procurement and prosecutions early instead of every drone attack first.

ACLED notes are shown here for the owner's own review (ADR 0006); nothing leaves the machine.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.label_review import actors, document_ids, interleave
from app.db.models import UXS_LABEL_ITEMS, Event, Source, UxsClassification, UxsLabel
from app.db.session import get_session

router = APIRouter(prefix="/uxs", tags=["uxs labels"])
DB = Annotated[Session, Depends(get_session)]


class UxsLabelIn(BaseModel):
    event_id: int
    verdict: Literal["correct", "partial", "incorrect"]
    wrong: list[str] = Field(default_factory=list, max_length=len(UXS_LABEL_ITEMS))
    note: str | None = Field(default=None, max_length=2000)


class UxsLabelOut(BaseModel):
    id: int
    event_id: int
    verdict: str
    wrong: list[str]
    judged_activity: str
    judged_platform: str
    judged_missions: list[str]
    judged_payloads: list[str]
    prompt_version: str | None
    note: str | None
    updated_at: dt.datetime


class UxsReviewItem(BaseModel):
    event_id: int
    source: str
    source_key: str
    event_date: dt.date
    event_type: str
    sub_event_type: str | None
    admin1_name: str | None
    admin2_name: str | None
    description: str | None
    actors: list[str]
    activity: str
    platform: str
    missions: list[str]
    payloads: list[str]
    evidence: str | None
    prompt_version: str | None
    document_ids: list[int]
    stratum: str
    label: UxsLabelOut | None
    # The event was reclassified after it was labeled: the label judged another verdict.
    stale: bool


class UxsReview(BaseModel):
    size: int
    labeled: int  # current labels only; a stale label is to do again
    strata: dict[str, int]
    items: list[UxsReviewItem]


def label_out(lab: UxsLabel) -> UxsLabelOut:
    return UxsLabelOut(
        id=lab.id,
        event_id=lab.event_id,
        verdict=lab.verdict,
        wrong=list(lab.wrong or []),
        judged_activity=lab.judged_activity,
        judged_platform=lab.judged_platform,
        judged_missions=list(lab.judged_missions or []),
        judged_payloads=list(lab.judged_payloads or []),
        prompt_version=lab.prompt_version,
        note=lab.note,
        updated_at=lab.updated_at,
    )


def judged_items(ev: Event) -> set[str]:
    """What a partly wrong label may name on this event."""
    return {"activity", "platform"} | set(ev.uxs_missions or []) | set(ev.uxs_payloads or [])


def _version(session: Session, ev: Event, slug: str) -> str | None:
    if slug != "acled":
        return ev.prompt_version
    uc = session.get(UxsClassification, ev.id)
    return uc.prompt_version if uc else None


@router.get("/review", response_model=UxsReview)
def review(
    session: DB,
    source: Annotated[Literal["all", "acled", "news"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> UxsReview:
    """Events with UxS fields, interleaved by activity (see module docstring)."""
    stmt = (
        select(Event, Source.slug, UxsClassification.evidence, UxsClassification.prompt_version)
        .join(Source, Source.id == Event.source_id)
        .outerjoin(UxsClassification, UxsClassification.event_id == Event.id)
        .where(Event.uxs_activity.is_not(None))
    )
    if source == "acled":
        stmt = stmt.where(Source.slug == "acled")
    elif source == "news":
        stmt = stmt.where(Source.slug != "acled")
    rows = session.execute(stmt).all()
    ids = [r[0].id for r in rows]
    labels = {
        lab.event_id: lab
        for lab in session.scalars(select(UxsLabel).where(UxsLabel.event_id.in_(ids)))
    }
    docs = document_ids(session, ids)
    counts, ordered = interleave(rows, lambda ev: ev.uxs_activity or "none")
    current = sum(1 for r in rows if (lab := labels.get(r[0].id)) and not lab.is_stale(r[0]))
    items: list[UxsReviewItem] = []
    for row in ordered[:limit]:
        ev: Any = row[0]
        slug, uc_evidence, uc_version = row[1], row[2], row[3]
        lab = labels.get(ev.id)
        items.append(
            UxsReviewItem(
                event_id=ev.id,
                source=slug,
                source_key=ev.source_key,
                event_date=ev.event_date,
                event_type=ev.event_type,
                sub_event_type=ev.sub_event_type,
                admin1_name=ev.admin1_name,
                admin2_name=ev.admin2_name,
                description=ev.description,
                actors=actors(ev, slug),
                activity=ev.uxs_activity,
                platform=ev.uxs_platform,
                missions=list(ev.uxs_missions or []),
                payloads=list(ev.uxs_payloads or []),
                evidence=uc_evidence if slug == "acled" else (ev.attributes or {}).get("evidence"),
                prompt_version=uc_version if slug == "acled" else ev.prompt_version,
                document_ids=docs.get(ev.id, []),
                stratum=ev.uxs_activity,
                label=label_out(lab) if lab else None,
                stale=lab.is_stale(ev) if lab else False,
            )
        )
    return UxsReview(size=len(rows), labeled=current, strata=counts, items=items)


@router.put("/labels", response_model=UxsLabelOut)
def put_label(body: UxsLabelIn, session: DB) -> UxsLabelOut:
    """Create or replace the label on one event's UxS verdict, freezing the verdict judged."""
    row = session.execute(
        select(Event, Source.slug)
        .join(Source, Source.id == Event.source_id)
        .where(Event.id == body.event_id)
    ).first()
    if row is None:
        raise HTTPException(404, "event not found")
    ev, slug = row
    if ev.uxs_activity is None or ev.uxs_platform is None:
        raise HTTPException(422, "event has no UxS fields to judge")
    wrong = sorted(set(body.wrong)) if body.verdict == "partial" else []
    if body.verdict == "partial" and not wrong:
        raise HTTPException(422, "a partly wrong label names the wrong items")
    if extra := set(wrong) - judged_items(ev):
        raise HTTPException(422, f"not in this verdict: {', '.join(sorted(extra))}")
    values = {
        "event_id": ev.id,
        "verdict": body.verdict,
        "wrong": wrong,
        "judged_activity": ev.uxs_activity,
        "judged_platform": ev.uxs_platform,
        "judged_missions": list(ev.uxs_missions or []),
        "judged_payloads": list(ev.uxs_payloads or []),
        "prompt_version": _version(session, ev, slug),
        "note": body.note,
    }
    ins = insert(UxsLabel).values(**values)
    stmt = ins.on_conflict_do_update(
        index_elements=[UxsLabel.event_id],
        set_={k: ins.excluded[k] for k in values if k != "event_id"} | {"updated_at": func.now()},
    ).returning(UxsLabel.id)
    label_id = session.scalar(stmt)
    session.commit()
    return label_out(session.get_one(UxsLabel, label_id))


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(label_id: int, session: DB) -> Response:
    lab = session.get(UxsLabel, label_id)
    if lab is None:
        raise HTTPException(404, "label not found")
    session.delete(lab)
    session.commit()
    return Response(status_code=204)
