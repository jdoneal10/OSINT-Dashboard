"""Pixtoday.net event exports (ADR 0010).

pixtoday.net disallows every agent in robots.txt, so nothing is fetched. The owner exports
``PiX_MEX_ActiveCartels_Events_<date>.csv`` while signed in and imports it:

    make ingest SOURCE=pixtoday FILE=path.csv

Each row is a PiX-written summary of one X post, with the post URL, PiX's cartel
attribution, categories and a mapped location. One post can appear on several rows (one per
mapped location); it becomes one ``documents`` row keyed by the post's status ID, so a later
export that overlaps an earlier one adds only the new posts. Documents then go through the
normal pipeline (filter, Haiku extraction, clustering, Admiralty). The owner's permission
covers processing with Claude (ADR 0010).

Rules applied here (ADR 0010):
- "Government / Military Operations" rows are dropped (CLAUDE.md rule 4). From "Security
  Operations" rows, extraction keeps only the TCO action (extraction rule 10).
- A row without an X post URL is dropped: every record must cite the underlying source.
- The source is graded D (an aggregator of social-media claims); clusters lift a report only
  when an independent source corroborates it. The same X post relayed by PiX and Dataminr
  counts once (``app.enrich.dedupe``).
- Victims and bystanders named in summaries never become persons (extraction safeguards,
  ADR 0013).
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Document
from app.db.session import session_factory
from app.ingest.articles import canonical_url
from app.ingest.raw import sha256_bytes, write_raw
from app.ingest.runs import file_already_ingested, ingest_run, source_id

log = logging.getLogger(__name__)

SOURCE = "pixtoday"
JOB = "pixtoday"
HEADER = (
    "DATA_COMPILED_BY", "event_group", "event_description", "event_date", "cartels_involved",
    "event_categories", "lat", "lon", "source", "symbol_group",
)  # fmt: skip
DROPPED_GROUP = "Government / Military Operations"
# X status IDs are snowflakes: milliseconds since this epoch, shifted left 22 bits.
TWITTER_EPOCH_MS = 1288834974657
X_STATUS = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([^/\s?#]+)/status/(\d+)", re.I
)
_SPANISH = re.compile(r"\b(el|la|los|las|del|que|por|con|una|para|tras|fue)\b", re.I)


class PixFormatError(ValueError):
    """The file is not a PiX events export."""


@dataclass
class PixPost:
    status_id: str
    url: str
    description: str
    posted_at: dt.datetime
    event_dates: list[dt.date] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    locations: list[tuple[float, float]] = field(default_factory=list)

    def title(self) -> str:
        first = re.split(r"(?<=[.!?])\s", self.description.strip(), maxsplit=1)[0]
        return first if len(first) <= 200 else first[:197].rstrip() + "..."

    def text(self) -> str:
        """The summary as PiX wrote it, then PiX's own record fields, labeled as PiX's."""
        record = [f"event date {', '.join(d.isoformat() for d in self.event_dates)}"]
        if self.organizations:
            record.append(f"organizations (PiX attribution) {', '.join(self.organizations)}")
        if self.categories:
            record.append(f"categories {', '.join(self.categories)}")
        return f"{self.description.strip()}\n\nPiX record: " + "; ".join(record) + "."


@dataclass
class PixExport:
    posts: list[PixPost]
    rows: int
    dropped_government: int
    dropped_no_source: int


def x_status(url: str) -> tuple[str, str] | None:
    """(handle, status ID) of an X post URL, or None."""
    m = X_STATUS.search(url)
    return (m.group(1), m.group(2)) if m else None


def posted_at(status_id: str) -> dt.datetime:
    ms = (int(status_id) >> 22) + TWITTER_EPOCH_MS
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC)


def _date(value: str) -> dt.date | None:
    value = value.strip()
    if not value:
        return None
    try:
        month, day, year = (int(x) for x in value[:10].split("/"))
        return dt.date(year, month, day)
    except ValueError as exc:  # also a wrong field count
        raise PixFormatError(f"event_date {value!r} is not MM/DD/YYYY") from exc


def _split(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip() and p.strip() != "Unknown"]


def _add(items: list[Any], new: list[Any]) -> None:
    items.extend(x for x in new if x not in items)


def parse_export(raw: str) -> PixExport:
    reader = csv.DictReader(io.StringIO(raw.removeprefix("﻿")))
    missing = [c for c in HEADER if c not in (reader.fieldnames or [])]
    if missing:
        raise PixFormatError(f"not a PiX events export; missing columns {missing}")
    posts: dict[str, PixPost] = {}
    rows = government = no_source = 0
    for row in reader:
        rows += 1
        if row["event_group"].strip() == DROPPED_GROUP:
            government += 1
            continue
        status = x_status(row["source"])
        if status is None:
            no_source += 1
            continue
        status_id = status[1]
        post = posts.get(status_id)
        if post is None:
            post = posts[status_id] = PixPost(
                status_id=status_id,
                url=X_STATUS.search(row["source"]).group(0),  # type: ignore[union-attr]
                description=row["event_description"],
                posted_at=posted_at(status_id),
            )
        day = _date(row["event_date"])
        _add(post.event_dates, [day] if day else [])
        _add(post.organizations, _split(row["cartels_involved"]))
        _add(post.categories, _split(row["event_categories"]))
        with contextlib.suppress(ValueError):  # a row without coordinates keeps its text
            _add(post.locations, [(float(row["lat"]), float(row["lon"]))])
    for post in posts.values():
        if not post.event_dates:  # PiX gave no date: the day the post went up
            post.event_dates.append(post.posted_at.date())
        post.event_dates.sort()
    return PixExport(list(posts.values()), rows, government, no_source)


def upsert_posts(session: Session, sid: int, export: PixExport, raw_path: str) -> int:
    """Insert new posts; a post already stored is left as it is. Returns inserted."""
    inserted = 0
    now = dt.datetime.now(dt.UTC)
    for post in export.posts:
        text = post.text()
        stmt = (
            insert(Document)
            .values(
                source_id=sid,
                source_key=f"x:{post.status_id}",
                source_url=post.url,
                canonical_url=canonical_url(post.url),
                retrieved_at=now,
                title=post.title(),
                summary=post.description.strip(),
                original_text=text,
                language="es" if len(_SPANISH.findall(post.description)) >= 3 else "en",
                published_at=post.posted_at,
                raw_path=raw_path,
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                text_policy="full",
                pipeline_status="new",
            )
            .on_conflict_do_nothing(constraint="uq_documents_source_key")
            .returning(Document.id)
        )
        if session.execute(stmt).first() is not None:
            inserted += 1
    return inserted


def run_file(path: Path) -> int:
    content = path.read_bytes()
    sha = sha256_bytes(content)
    entry: dict[str, Any] = {"name": path.name, "sha256": sha}
    with ingest_run(JOB, source_slug=SOURCE, params={"files": []}) as run:
        if file_already_ingested(JOB, sha):
            run.params["files"].append(entry | {"skipped": "already ingested"})
            return 0
        export = parse_export(content.decode("utf-8"))
        snap = write_raw(SOURCE, run.id, path.name, content)
        run.raw_paths.append(str(snap.path))
        with session_factory()() as session, session.begin():
            run.inserted = upsert_posts(session, source_id(session, SOURCE), export, str(snap.path))
        entry |= {
            "rows": export.rows,
            "posts": len(export.posts),
            "inserted": run.inserted,
            "dropped_government_operations": export.dropped_government,
            "dropped_no_source": export.dropped_no_source,
        }
        run.params["files"].append(entry)
        log.info("pixtoday %s: %s", path.name, entry)
    return 0
