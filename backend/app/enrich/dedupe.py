"""Near-duplicate documents and event clustering (corroboration groups).

Documents: a 64-bit SimHash over word 3-shingles. A document within ``SIMHASH_BITS`` bits of
an earlier one (last ``WINDOW_DAYS`` days) is marked ``duplicate_of_id`` and skipped by the
filter and extraction, so syndicated copies are never counted as corroboration.

Events: news-derived events (never ACLED; ADR 0003) join an existing cluster when they fall
within +/-1 day, 25 km and a compatible event type; otherwise they start a new cluster.
Cluster statistics (documents, independent sources, conflicting details) feed Admiralty
scoring and the Sonnet escalation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    ClusterAssessment,
    Document,
    Event,
    EventCluster,
    Source,
    event_documents,
)

log = logging.getLogger(__name__)

SIMHASH_BITS = 3  # max Hamming distance for "same text"
WINDOW_DAYS = 14
CLUSTER_KM = 25
CLUSTER_DAYS = 1
VIOLENT = {"Battles", "Violence against civilians", "Explosions/Remote violence"}
_WORD = re.compile(r"\w+", re.UNICODE)


# --------------------------------------------------------------------------- documents


def simhash(text_value: str) -> int:
    words = [w.lower() for w in _WORD.findall(text_value)]
    shingles = [" ".join(words[i : i + 3]) for i in range(max(1, len(words) - 2))]
    weights = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if h >> bit & 1 else -1
    return sum(1 << bit for bit, w in enumerate(weights) if w > 0)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _doc_text(doc: Document) -> str:
    return " ".join(x for x in (doc.title, doc.original_text or doc.summary) if x)


def mark_duplicates(session: Session) -> int:
    """Mark new documents that repeat an earlier document's text. Returns duplicates found."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=WINDOW_DAYS)
    docs = list(
        session.scalars(
            select(Document)
            .where(Document.retrieved_at >= since, Document.duplicate_of_id.is_(None))
            .order_by(Document.published_at.asc().nulls_last(), Document.id)
        )
    )
    seen: list[tuple[int, int]] = []  # (simhash, doc id) of originals
    found = 0
    for doc in docs:
        body = _doc_text(doc)
        if len(body) < 200:  # too short to fingerprint reliably
            continue
        h = simhash(body)
        original = next((oid for oh, oid in seen if hamming(h, oh) <= SIMHASH_BITS), None)
        if original is not None and doc.pipeline_status == "new":
            doc.duplicate_of_id = original
            doc.pipeline_status = "skipped"
            found += 1
        else:
            seen.append((h, doc.id))
    return found


# --------------------------------------------------------------------------- events


def _compatible(a: str, b: str) -> bool:
    return a == b or (a in VIOLENT and b in VIOLENT)


def _candidate_cluster(session: Session, ev: Event) -> EventCluster | None:
    if ev.geom is None:
        return None
    rows = session.execute(
        text(
            """
            SELECT c.id, c.event_type FROM event_clusters c
            WHERE c.centroid IS NOT NULL
              AND c.first_date <= :d + :days AND c.last_date >= :d - :days
              AND ST_DWithin(c.centroid, (SELECT geom FROM events WHERE id = :eid), :meters)
            ORDER BY ST_Distance(c.centroid, (SELECT geom FROM events WHERE id = :eid))
            """
        ),
        {"d": ev.event_date, "days": CLUSTER_DAYS, "eid": ev.id, "meters": CLUSTER_KM * 1000},
    ).all()
    for cid, ctype in rows:
        if _compatible(ctype, ev.event_type):
            return session.get_one(EventCluster, cid)
    return None


def refresh_cluster(session: Session, cluster: EventCluster) -> None:
    """Recompute dates, centroid, counts and conflicts from member events."""
    members = list(session.scalars(select(Event).where(Event.cluster_id == cluster.id)))
    cluster.n_events = len(members)
    cluster.first_date = min(e.event_date for e in members)
    cluster.last_date = max(e.event_date for e in members)
    docs = session.execute(
        select(event_documents.c.document_id, Document.source_id)
        .join(Document, Document.id == event_documents.c.document_id)
        .where(event_documents.c.event_id.in_([e.id for e in members]))
    ).all()
    cluster.n_documents = len({d for d, _ in docs})
    cluster.n_independent_sources = len({s for _, s in docs})
    grades = session.scalars(
        select(Source.reliability).where(Source.id.in_({s for _, s in docs}))
    ).all()
    cluster.reliability = min(grades) if grades else None
    session.flush()
    session.execute(
        text(
            """
            UPDATE event_clusters SET centroid = sub.c FROM (
              SELECT ST_Centroid(ST_Collect(geom::geometry))::geography AS c
              FROM events WHERE cluster_id = :cid AND geom IS NOT NULL) sub
            WHERE id = :cid
            """
        ),
        {"cid": cluster.id},
    )
    conflicts: dict[str, Any] = {}
    fatalities = sorted({e.fatalities for e in members if e.fatalities is not None})
    if len(fatalities) > 1:
        conflicts["fatalities"] = fatalities
    places = sorted({e.admin2_code for e in members if e.admin2_code})
    if len(places) > 1:
        conflicts["municipality"] = places
    types = sorted({e.event_type for e in members})
    if len(types) > 1:
        conflicts["event_type"] = types
    cluster.conflicts = conflicts
    admin1 = {e.admin1_code for e in members if e.admin1_code}
    cluster.admin1_code = admin1.pop() if len(admin1) == 1 else None


def prune_clusters(session: Session) -> int:
    """Repair clusters whose members changed outside clustering (re-extraction deletes events).

    Empty clusters are deleted (their assessments cascade); clusters that lost members are
    refreshed and their assessments dropped so the analysis re-runs on the current reports.
    """
    actual = select(func.count()).where(Event.cluster_id == EventCluster.id).scalar_subquery()
    stale = list(session.scalars(select(EventCluster).where(EventCluster.n_events != actual)))
    for cluster in stale:
        if session.scalar(select(func.count()).where(Event.cluster_id == cluster.id)):
            session.execute(
                delete(ClusterAssessment).where(ClusterAssessment.cluster_id == cluster.id)
            )
            refresh_cluster(session, cluster)
        else:
            session.delete(cluster)
    session.flush()
    return len(stale)


def cluster_events(session: Session) -> dict[str, int]:
    """Assign unclustered document-derived events to clusters.

    A cluster that gains members loses its assessment, so the analysis re-runs with them.
    """
    pruned = prune_clusters(session)
    acled = session.scalar(select(Source.id).where(Source.slug == "acled"))
    has_doc = select(event_documents.c.event_id).where(event_documents.c.event_id == Event.id)
    events = list(
        session.scalars(
            select(Event)
            .where(Event.cluster_id.is_(None), Event.source_id != acled, has_doc.exists())
            .order_by(Event.event_date, Event.id)
        )
    )
    counts = {"joined": 0, "new": 0}
    touched: set[int] = set()
    for ev in events:
        cluster = _candidate_cluster(session, ev)
        if cluster is None:
            cluster = EventCluster(
                first_date=ev.event_date,
                last_date=ev.event_date,
                event_type=ev.event_type,
                admin1_code=ev.admin1_code,
            )
            session.add(cluster)
            session.flush()
            if ev.geom is not None:
                session.execute(
                    text("UPDATE event_clusters SET centroid = (SELECT geom FROM events "
                         "WHERE id = :eid) WHERE id = :cid"),
                    {"eid": ev.id, "cid": cluster.id},
                )  # fmt: skip
            counts["new"] += 1
        else:
            counts["joined"] += 1
            session.execute(
                delete(ClusterAssessment).where(ClusterAssessment.cluster_id == cluster.id)
            )
        ev.cluster_id = cluster.id
        session.flush()
        touched.add(cluster.id)
    for cid in touched:
        refresh_cluster(session, session.get_one(EventCluster, cid))
    log.info("clustering: %s (%d touched, %d pruned)", counts, len(touched), pruned)
    return counts
