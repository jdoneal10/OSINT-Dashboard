"""Shared helpers for the topic label reviews (grid, ADR 0014; UxS, ADR 0009 amendment 1)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, event_documents
from app.enrich.acled_notes import ACTOR_KEYS


def actors(ev: Event, slug: str) -> list[str]:
    """ACLED's actor dyad, or the perpetrators and targets news extraction recorded."""
    attrs = ev.attributes or {}
    if slug == "acled":
        return [str(attrs[k]) for k in ACTOR_KEYS if attrs.get(k)]
    return [str(a) for a in (attrs.get("perpetrators") or []) + (attrs.get("targets") or [])]


def document_ids(session: Session, event_ids: list[int]) -> dict[int, list[int]]:
    """The documents each event was derived from (none for ACLED), sorted."""
    docs: dict[int, list[int]] = defaultdict(list)
    for ev_id, doc_id in session.execute(
        select(event_documents.c.event_id, event_documents.c.document_id).where(
            event_documents.c.event_id.in_(event_ids)
        )
    ):
        docs[ev_id].append(doc_id)
    return {k: sorted(v) for k, v in docs.items()}


def _rank(event_id: int) -> str:
    return hashlib.sha256(f"grid-label-sample:{event_id}".encode()).hexdigest()


def interleave(
    rows: Sequence[Any], stratum: Callable[[Event], str]
) -> tuple[dict[str, int], list[Any]]:
    """Group rows (whose first element is the event) by stratum, each group in stable hash
    order, and interleave the groups round-robin. Returns the stratum counts and the order.

    Labeling from the top then covers the rare strata early. The hash seed is the one the grid
    review first used, so its order is unchanged.
    """
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: _rank(r[0].id)):
        groups[stratum(row[0])].append(row)
    counts = {k: len(v) for k, v in sorted(groups.items())}
    queues = [list(groups[k]) for k in sorted(groups)]
    ordered: list[Any] = []
    while any(queues):
        for q in queues:
            if q:
                ordered.append(q.pop(0))
    return counts, ordered
