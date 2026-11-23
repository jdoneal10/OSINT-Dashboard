"""The calendar day a report was published where it was written (ADR 0004 amendment 2).

``published_at`` is stored in UTC, which is already tomorrow for an evening report in
Mexico. Each feed declares the time zone of its newsroom in ``feeds.yaml``; every date
derived from a report (the day shown to the model, fallback event and seizure dates,
"reported on") uses that day.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from app.db.models import Document
from app.ingest import feeds

# Sources without a feed entry. Dataminr alerts span the AOI, which is mostly UTC-6.
_OTHER_ZONES = {"dataminr": "America/Mexico_City"}
_WEEKDAYS = (
    "Monday (lunes)", "Tuesday (martes)", "Wednesday (miércoles)", "Thursday (jueves)",
    "Friday (viernes)", "Saturday (sábado)", "Sunday (domingo)",
)  # fmt: skip
_PAGE_TIMES = (
    re.compile(r"<meta(?=[^>]*article:published_time)[^>]*content=[\"']([^\"']+)[\"']", re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
)
# cbp.gov: "Release Date  Tue, 11/10/2026". Metadata extraction read that as 11 October.
_RELEASE_DATE = re.compile(r"Release Date(?:\s|<[^>]*>)*([A-Z][a-z]{2}), (\d\d)/(\d\d)/(\d{4})")


def zone_for(slug: str) -> ZoneInfo:
    if slug in _OTHER_ZONES:
        return ZoneInfo(_OTHER_ZONES[slug])
    return ZoneInfo(next((f.timezone for f in feeds.load_feeds() if f.slug == slug), "UTC"))


def _local(doc: Document, slug: str) -> tuple[dt.date, dt.time | None]:
    """The local day, and the local time when the source gave one."""
    moment = doc.published_at or doc.retrieved_at
    utc = moment.astimezone(dt.UTC)
    # A bare date is stored as exactly midnight UTC; converting it would give the day before.
    if slug not in _OTHER_ZONES and doc.published_at and utc.time() == dt.time(0):
        return utc.date(), None
    local = utc.astimezone(zone_for(slug))
    return local.date(), local.time() if doc.published_at else None


def published_day(doc: Document, slug: str) -> dt.date:
    return _local(doc, slug)[0]


def describe(doc: Document, slug: str) -> str:
    """The date line shown to the model. Keep it one line: a calendar of the days before it
    made the model judge relevant reports irrelevant (ADR 0004 amendment 2).
    """
    if not doc.published_at:
        return "PUBLISHED: unknown"
    day, time = _local(doc, slug)
    head = f"PUBLISHED: {day} {_WEEKDAYS[day.weekday()]}"
    if time:
        head += f", {time:%H:%M} local time"
    return head


def page_time(page: str, seen: dt.datetime) -> dt.datetime:
    """The article page's own publication time, else ``seen`` (when GDELT saw the article)."""
    if m := next(filter(None, (p.search(page) for p in _PAGE_TIMES)), None):
        try:
            stated = dt.datetime.fromisoformat(m[1].strip())
        except ValueError:
            return seen
        if stated.tzinfo and stated <= seen:
            return stated.astimezone(dt.UTC)
    return seen


def release_date(page: str) -> dt.datetime | None:
    """A U.S. month-first release date, accepted only if its stated weekday matches."""
    if not (m := _RELEASE_DATE.search(page)):
        return None
    try:
        day = dt.date(int(m[4]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    if not _WEEKDAYS[day.weekday()].startswith(m[1]):
        return None
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)
