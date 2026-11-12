"""Admiralty grading of event clusters (NATO / Admiralty system; CLAUDE.md analytic standards).

Reliability (A-F) is the best grade among the cluster's sources. Credibility (1-6):

| credibility | rule |
|---|---|
| 1 confirmed | >= 3 independent sources, no conflicting details |
| 2 probably true | 2 independent sources and no conflicts; or one A-grade source |
| 3 possibly true | one B-grade source; or several sources that conflict |
| 4 doubtful | one C-grade source |
| 6 cannot be judged | one source graded D-F, or no source |

Grade 5 (improbable) is reserved for analyst or Sonnet judgments that contradict the report;
rules alone never assign it. Syndicated copies were removed by dedupe, so "independent"
means distinct outlets. An attached ACLED event counts as one more source (ADR 0006); ACLED
may code from the same articles, which the Sonnet assessment weighs. Single-source claims
stay low whatever their prominence.

The grade is copied onto the cluster's news-derived events only; ACLED rows keep ACLED's
own values.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event, EventCluster, event_documents

CONFIDENCE = {
    1: Decimal("0.95"),
    2: Decimal("0.80"),
    3: Decimal("0.60"),
    4: Decimal("0.40"),
    5: Decimal("0.20"),
    6: None,
}


def credibility(n_independent: int, reliability: str | None, conflicted: bool) -> int:
    if n_independent >= 3 and not conflicted:
        return 1
    if n_independent >= 2:
        return 3 if conflicted else 2
    if n_independent == 1:
        return {"A": 2, "B": 3, "C": 4}.get(reliability or "F", 6)
    return 6


def score_clusters(session: Session, cluster_ids: list[int] | None = None) -> int:
    """Grade clusters and copy the grade onto member events. Returns clusters scored."""
    q = select(EventCluster)
    if cluster_ids is not None:
        q = q.where(EventCluster.id.in_(cluster_ids))
    n = 0
    for cluster in session.scalars(q):
        cred = credibility(
            cluster.n_independent_sources, cluster.reliability, bool(cluster.conflicts)
        )
        cluster.credibility = cred
        cluster.confidence = CONFIDENCE[cred]
        news = select(event_documents.c.event_id).where(event_documents.c.event_id == Event.id)
        for ev in session.scalars(
            select(Event).where(Event.cluster_id == cluster.id, news.exists())
        ):
            ev.credibility = cred
            ev.confidence = CONFIDENCE[cred]
        n += 1
    session.flush()
    return n
