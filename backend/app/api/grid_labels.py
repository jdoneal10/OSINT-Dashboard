"""Owner labels on grid verdicts (ADR 0014 step 6): the review list and label writes.

A grid label judges one event's grid-interaction kind and energy indicators, whether they came
from the ACLED grid pass or from news extraction (extract-v11). Only events with a kind or an
indicator are reviewed: the labels measure precision, not recall.

The review list is a deterministic sample: events are grouped by stratum (the kind, or the
first indicator when there is no kind), each group in stable hash order, and the groups are
interleaved, so labeling from the top covers the rare kinds early instead of 300 fuel-theft
records first.

ACLED notes are shown here for the owner's own review (ADR 0006); nothing leaves the machine.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.label_review import actors, document_ids, interleave
from app.db.models import GRID_LABEL_ITEMS, Event, GridClassification, GridLabel, Source
from app.db.session import get_session

router = APIRouter(prefix="/grid", tags=["grid labels"])
DB = Annotated[Session, Depends(get_session)]


class GridLabelIn(BaseModel):
    event_id: int
    verdict: Literal["correct", "partial", "incorrect"]
    wrong: list[str] = Field(default_factory=list, max_length=len(GRID_LABEL_ITEMS))
    note: str | None = Field(default=None, max_length=2000)


class GridLabelOut(BaseModel):
    id: int
    event_id: int
    verdict: str
    wrong: list[str]
    judged_kind: str | None
    judged_indicators: list[str]
    prompt_version: str | None
    note: str | None
    updated_at: dt.datetime


class GridReviewItem(BaseModel):
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
    kind: str | None
    indicators: list[str]
    evidence: str | None
    prompt_version: str | None
    document_ids: list[int]
    stratum: str
    label: GridLabelOut | None
    # The event was reclassified after it was labeled: the label judged another verdict.
    stale: bool


class GridReview(BaseModel):
    size: int
    labeled: int  # current labels only; a stale label is to do again
    strata: dict[str, int]
    items: list[GridReviewItem]


def label_out(lab: GridLabel) -> GridLabelOut:
    return GridLabelOut(
        id=lab.id,
        event_id=lab.event_id,
        verdict=lab.verdict,
        wrong=list(lab.wrong or []),
        judged_kind=lab.judged_kind,
        judged_indicators=list(lab.judged_indicators or []),
        prompt_version=lab.prompt_version,
        note=lab.note,
        updated_at=lab.updated_at,
    )


def has_grid_output() -> Any:
    return or_(Event.grid_interaction.is_not(None), func.cardinality(Event.energy_indicators) > 0)


def stratum(kind: str | None, indicators: list[str]) -> str:
    return kind or (indicators[0] if indicators else "none")


def _version(session: Session, ev: Event, slug: str) -> str | None:
    if slug != "acled":
        return ev.prompt_version
    gc = session.get(GridClassification, ev.id)
    return gc.prompt_version if gc else None


@router.get("/review", response_model=GridReview)
def review(
    session: DB,
    source: Annotated[Literal["all", "acled", "news"], Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> GridReview:
    """Events with a grid kind or indicator, interleaved by stratum (see module docstring)."""
    stmt = (
        select(Event, Source.slug, GridClassification.evidence, GridClassification.prompt_version)
        .join(Source, Source.id == Event.source_id)
        .outerjoin(GridClassification, GridClassification.event_id == Event.id)
        .where(has_grid_output())
    )
    if source == "acled":
        stmt = stmt.where(Source.slug == "acled")
    elif source == "news":
        stmt = stmt.where(Source.slug != "acled")
    rows = session.execute(stmt).all()
    ids = [r[0].id for r in rows]
    labels = {
        lab.event_id: lab
        for lab in session.scalars(select(GridLabel).where(GridLabel.event_id.in_(ids)))
    }
    docs = document_ids(session, ids)
    counts, ordered = interleave(
        rows, lambda ev: stratum(ev.grid_interaction, list(ev.energy_indicators or []))
    )
    current = sum(1 for r in rows if (lab := labels.get(r[0].id)) and not lab.is_stale(r[0]))
    items = []
    for ev, slug, gc_evidence, gc_version in ordered[:limit]:
        lab = labels.get(ev.id)
        indicators = list(ev.energy_indicators or [])
        items.append(
            GridReviewItem(
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
                kind=ev.grid_interaction,
                indicators=indicators,
                evidence=gc_evidence if slug == "acled" else (ev.attributes or {}).get("evidence"),
                prompt_version=gc_version if slug == "acled" else ev.prompt_version,
                document_ids=docs.get(ev.id, []),
                stratum=stratum(ev.grid_interaction, indicators),
                label=label_out(lab) if lab else None,
                stale=lab.is_stale(ev) if lab else False,
            )
        )
    return GridReview(
        size=len(rows),
        labeled=current,  # stale labels are to do again
        strata=counts,
        items=items,
    )


@router.put("/labels", response_model=GridLabelOut)
def put_label(body: GridLabelIn, session: DB) -> GridLabelOut:
    """Create or replace the label on one event's grid verdict, freezing the verdict judged."""
    row = session.execute(
        select(Event, Source.slug)
        .join(Source, Source.id == Event.source_id)
        .where(Event.id == body.event_id)
    ).first()
    if row is None:
        raise HTTPException(404, "event not found")
    ev, slug = row
    indicators = list(ev.energy_indicators or [])
    if ev.grid_interaction is None and not indicators:
        raise HTTPException(422, "event has no grid kind or indicator to judge")
    wrong = sorted(set(body.wrong)) if body.verdict == "partial" else []
    judged = ({"kind"} if ev.grid_interaction else set()) | set(indicators)
    if body.verdict == "partial" and not wrong:
        raise HTTPException(422, "a partly wrong label names the wrong items")
    if extra := set(wrong) - judged:
        raise HTTPException(422, f"not in this verdict: {', '.join(sorted(extra))}")
    values = {
        "event_id": ev.id,
        "verdict": body.verdict,
        "wrong": wrong,
        "judged_kind": ev.grid_interaction,
        "judged_indicators": indicators,
        "prompt_version": _version(session, ev, slug),
        "note": body.note,
    }
    ins = insert(GridLabel).values(**values)
    stmt = ins.on_conflict_do_update(
        index_elements=[GridLabel.event_id],
        set_={k: ins.excluded[k] for k in values if k != "event_id"} | {"updated_at": func.now()},
    ).returning(GridLabel.id)
    label_id = session.scalar(stmt)
    session.commit()
    return label_out(session.get_one(GridLabel, label_id))


@router.delete("/labels/{label_id}", status_code=204)
def delete_label(label_id: int, session: DB) -> Response:
    lab = session.get(GridLabel, label_id)
    if lab is None:
        raise HTTPException(404, "label not found")
    session.delete(lab)
    session.commit()
    return Response(status_code=204)
