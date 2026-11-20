"""Dataminr First Alert interval digests (ADR 0012).

The owner's Gmail connector saves each digest email body as a ``.txt`` file in
``data/raw/dataminr/inbox/``. This module parses those files into alerts and stores each
alert as a ``documents`` row. It never touches the mailbox and makes no outbound call.

    make ingest SOURCE=dataminr                # process every file in the inbox
    make ingest SOURCE=dataminr FILE=path.txt  # one file from anywhere

Per file: hash check (a re-delivered file is not ingested twice) -> parse -> copy to
``data/raw/dataminr/<date>/`` -> upsert alerts by Dataminr alert ID -> remove from inbox.
A file that does not parse is moved to ``inbox/failed/`` and the run is marked as an error.

Rules applied here (ADR 0012):
- X-sourced alerts about protests, rallies, marches, strikes or sit-ins are dropped (First
  Alert third-party notice). Blockades are kept: cartel blockades are threat activity.
- First Alert redirect links (they carry an account key) and alert images are never stored.
- A missing digest window between received digests raises a ``feed_gap`` alert; no
  new digest for ``STALL_HOURS`` raises ``feed_stalled``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Alert, Document, IngestRun
from app.db.session import session_factory
from app.ingest.articles import canonical_url
from app.ingest.raw import sha256_bytes, write_raw
from app.ingest.runs import RunContext, file_already_ingested, ingest_run, source_id

log = logging.getLogger(__name__)

SOURCE = "dataminr"
JOB = "dataminr"
# Digests cover 12-hour windows (00:00-12:00 and 12:00-24:00 HST) and the owner's connector
# saves them at 00:45 and 12:45 HST, so a healthy feed is at most ~13 h behind. 15 h flags one
# missed delivery about two hours late without firing just before each on-time delivery.
STALL_HOURS = 15
GAP_LOOKBACK_DAYS = 14

# Time-zone abbreviations First Alert may print, mapped to IANA zones.
TIMEZONES = {
    "HST": "Pacific/Honolulu",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "UTC": "UTC",
    "GMT": "UTC",
}
LANGUAGES = {"SPANISH": "es", "ENGLISH": "en", "PORTUGUESE": "pt", "FRENCH": "fr"}
_MONTH_NAMES = (
    "January February March April May June July August September October November December"
)
MONTHS = {name: i for i, name in enumerate(_MONTH_NAMES.split(), start=1)}

_IMAGE = re.compile(r"\[https?://[^\]]*\]")
_WINDOW = re.compile(
    r"^(?P<watchlist>.+?) \| (?P<m1>[A-Z][a-z]+) (?P<d1>\d{1,2}), (?P<t1>\d{2}:\d{2}) - "
    r"(?P<m2>[A-Z][a-z]+) (?P<d2>\d{1,2}), (?P<t2>\d{2}:\d{2}) \((?P<tz>[A-Z]{2,4})\)$"
)
_TOTAL = re.compile(r"\b(\d+) total alerts?\b")
_BODY_START = re.compile(r"^\d+ new alerts?\b")
_PRIORITY = re.compile(r"^(?P<level>Alert|Urgent|Flash)(?P<update> Update)?$")
_STAMP = re.compile(
    r"^(?P<h>\d{1,2}):(?P<mi>\d{2})(?P<ap>[ap]m) (?P<mon>[A-Z][a-z]+) (?P<d>\d{1,2}), "
    r"(?P<y>\d{4}) (?P<tz>[A-Z]{2,4})$"
)
_POST = re.compile(r"^Original Public Post(?: \(.*\))?$")
_TRANSLATED = re.compile(r"^Translated From (?P<lang>[A-Z]+):$")
_EXCERPT = re.compile(r"^Excerpt From (?P<what>.+):$")
_LINK = re.compile(r"^(?P<label>[^<>]+?) <(?P<url>https?://[^>\s]+)>$")
_CAPTION = re.compile(r"^(?P<what>.+): (?P<kind>[^:]+?) via (?P<via>[^:]+?)\.?$")
_END = re.compile(r"^(- )+-$")
_NO_LINK_NOTE = "Open in First Alert to view link to original public source"

# Protest-type events. Deliberately not "blockade" (narcobloqueos are threat activity) and
# not bare "strike" (laser and drone strikes are priority threats).
PROTEST = re.compile(
    r"\b(protest\w*|demonstrat\w*|rall(?:y|ies)|march(?:es|ed|ers)?(?!\s+\d)|sit-ins?|"
    r"picket\w*|(?:labor|labour|general|hunger|workers'?|teachers'?|transport) strikes?|"
    r"on strike|strikers?)\b",
    re.IGNORECASE,
)
_DATAMINR_HOSTS = ("dataminr.com",)


class DataminrFormatError(ValueError):
    """A digest file does not have the expected First Alert layout."""


@dataclass
class DigestAlert:
    alert_id: str
    level: str  # Alert | Urgent | Flash
    is_update: bool
    occurred_at: dt.datetime  # UTC
    place: str | None
    caption: str
    source_kind: str | None  # e.g. "Local News Outlet Photo"
    platform: str | None  # e.g. "Facebook", "X", "Public Telegram Board"
    post_original: str | None = None
    post_language: str | None = None
    post_english: str | None = None
    excerpt: str | None = None
    excerpt_from: str | None = None
    original_url: str | None = None

    @property
    def x_protest(self) -> bool:
        """An X-sourced protest/rally alert, dropped under the First Alert X term."""
        return (self.platform or "").strip() == "X" and bool(PROTEST.search(self.caption))

    def text(self) -> str:
        """Document text for the pipeline. Links and Dataminr markup are left out."""
        parts = [self.caption]
        if self.place:
            parts.append(f"Place: {self.place}")
        if self.source_kind or self.platform:
            parts.append(f"Reported by: {self.source_kind or '?'} via {self.platform or '?'}")
        parts.append(f"Dataminr priority: {self.level}" + (" (update)" if self.is_update else ""))
        if self.post_original:
            lang = self.post_language or "unknown language"
            parts.append(f"Original post ({lang}; excerpt, may be cut off):\n{self.post_original}")
        if self.post_english:
            label = "Dataminr English translation" if self.post_original else "Original post"
            parts.append(f"{label} (excerpt):\n{self.post_english}")
        if self.excerpt:
            parts.append(f"Excerpt from {self.excerpt_from or 'source'}:\n{self.excerpt}")
        return "\n\n".join(parts)


@dataclass
class Digest:
    watchlist: str
    window_start: dt.datetime  # UTC
    window_end: dt.datetime  # UTC
    total: int | None
    alerts: list[DigestAlert] = field(default_factory=list)


# --------------------------------------------------------------------------- parsing


def _zone(abbrev: str) -> ZoneInfo:
    name = TIMEZONES.get(abbrev)
    if name is None:
        raise DataminrFormatError(f"unknown time zone {abbrev!r}")
    return ZoneInfo(name)


def _month(name: str) -> int:
    if name not in MONTHS:
        raise DataminrFormatError(f"unknown month {name!r}")
    return MONTHS[name]


def _stamp(m: re.Match[str]) -> dt.datetime:
    hour = int(m["h"]) % 12 + (12 if m["ap"] == "pm" else 0)
    local = dt.datetime(
        int(m["y"]), _month(m["mon"]), int(m["d"]), hour, int(m["mi"]), tzinfo=_zone(m["tz"])
    )
    return local.astimezone(dt.UTC)


def _window_point(month: str, day: str, hhmm: str, year: int, tz: ZoneInfo) -> dt.datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return dt.datetime(year, _month(month), int(day), hh, mm, tzinfo=tz).astimezone(dt.UTC)


def _clean(raw: str) -> list[str]:
    lines = (_IMAGE.sub("", line).strip() for line in raw.replace("\r\n", "\n").split("\n"))
    return [line for line in lines if line]


def _alert_id(urls: list[str]) -> str | None:
    for url in urls:
        ids = parse_qs(urlsplit(url).query).get("alertId")
        if ids:
            return ids[0]
    return None


def _is_dataminr(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in _DATAMINR_HOSTS)


@dataclass
class _Sections:
    post: list[str] = field(default_factory=list)
    translated: list[str] = field(default_factory=list)
    excerpt: list[str] = field(default_factory=list)
    language: str | None = None
    excerpt_from: str | None = None
    redirect_urls: list[str] = field(default_factory=list)
    original_url: str | None = None


def _read_sections(lines: list[str]) -> _Sections:
    """Post, translation and excerpt text, and the links, after an alert's caption."""
    out = _Sections()
    current: list[str] | None = None
    for line in lines:
        if _POST.match(line):
            current = out.post
        elif t := _TRANSLATED.match(line):
            current, out.language = out.translated, t["lang"]
        elif e := _EXCERPT.match(line):
            current, out.excerpt_from = out.excerpt, e["what"]
        elif link := _LINK.match(line):
            current = None
            if _is_dataminr(link["url"]):
                out.redirect_urls.append(link["url"])
            elif out.original_url is None and link["label"].startswith("View on "):
                out.original_url = link["url"]
        elif line == _NO_LINK_NOTE:
            current = None
        elif current is not None:
            current.append(line)
    return out


def _split_place(stamp: str, rest: list[str]) -> tuple[str | None, str, list[str]]:
    """(place, caption, remaining lines). The place line comes first unless the alert has
    none, in which case the caption is first."""
    if rest and _CAPTION.match(rest[0]) and (len(rest) == 1 or not _CAPTION.match(rest[1])):
        return None, rest[0], rest[1:]
    if len(rest) >= 2:
        return rest[0], rest[1], rest[2:]
    raise DataminrFormatError(f"alert at {stamp} has no caption")


def _parse_alert(prio: re.Match[str], stamp: re.Match[str], rest: list[str]) -> DigestAlert:
    place, caption, rest = _split_place(stamp.string, rest)
    cap = _CAPTION.match(caption)
    sec = _read_sections(rest)
    alert_id = _alert_id(sec.redirect_urls)
    if alert_id is None:  # no First Alert link: fall back to a content hash
        key = f"{stamp.string}|{caption}".encode()
        alert_id = "h-" + hashlib.sha256(key).hexdigest()[:32]

    post = "\n".join(sec.post) or None
    translated = "\n".join(sec.translated) or None
    # First Alert labels Dataminr's English rendering "Original Public Post" and the post as
    # written "Translated From <LANGUAGE>". Store each under what it actually is.
    if translated:
        post_original, post_language, post_english = translated, sec.language, post
    else:
        post_original, post_language, post_english = None, None, post
    return DigestAlert(
        alert_id=alert_id,
        level=prio["level"],
        is_update=bool(prio["update"]),
        occurred_at=_stamp(stamp),
        place=place,
        caption=caption,
        source_kind=cap["kind"].strip() if cap else None,
        platform=cap["via"].strip() if cap else None,
        post_original=post_original,
        post_language=post_language,
        post_english=post_english,
        excerpt="\n".join(sec.excerpt) or None,
        excerpt_from=sec.excerpt_from,
        original_url=sec.original_url,
    )


def parse_digest(raw: str) -> Digest:
    lines = _clean(raw)
    window = next((m for line in lines if (m := _WINDOW.match(line))), None)
    if window is None:
        raise DataminrFormatError("no digest window line (e.g. 'Watchlist | November 16, ...')")
    total_m = next((m for line in lines if (m := _TOTAL.search(line))), None)
    try:
        start = next(i for i, line in enumerate(lines) if _BODY_START.match(line)) + 1
    except StopIteration as exc:
        raise DataminrFormatError("no 'N new alerts' line before the alert list") from exc

    alerts: list[DigestAlert] = []
    body = lines[start:]
    heads: list[tuple[int, re.Match[str], re.Match[str]]] = []
    for i, line in enumerate(body):
        if _END.match(line):
            body = body[:i]
            break
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if (prio := _PRIORITY.match(line)) and (stamp := _STAMP.match(nxt)):
            heads.append((i, prio, stamp))
    for n, (at, prio, stamp) in enumerate(heads):
        stop = heads[n + 1][0] if n + 1 < len(heads) else len(body)
        alerts.append(_parse_alert(prio, stamp, body[at + 2 : stop]))

    total = int(total_m[1]) if total_m else None
    if total is not None and total != len(alerts):
        raise DataminrFormatError(f"digest says {total} alerts but {len(alerts)} were parsed")

    # The window line has no year; take it from the alerts (or the current year) and step
    # back a year when the window month is after the alert month (a digest spanning 1 Jan).
    tz = _zone(window["tz"])
    ref = alerts[0].occurred_at.astimezone(tz) if alerts else dt.datetime.now(tz)

    def year_for(month: str) -> int:
        return ref.year - 1 if _month(month) > ref.month else ref.year

    w_start = _window_point(window["m1"], window["d1"], window["t1"], year_for(window["m1"]), tz)
    w_end = _window_point(window["m2"], window["d2"], window["t2"], year_for(window["m2"]), tz)
    if w_end <= w_start:
        raise DataminrFormatError("digest window ends before it starts")
    return Digest(window["watchlist"].strip(), w_start, w_end, total, alerts)


# --------------------------------------------------------------------------- storing


def upsert_alerts(session: Session, sid: int, digest: Digest, raw_path: str) -> tuple[int, int]:
    """Insert new alerts; an alert ID already stored is left as it is. Returns
    (inserted, dropped_x_protest)."""
    inserted = dropped = 0
    now = dt.datetime.now(dt.UTC)
    for alert in digest.alerts:
        if alert.x_protest:
            dropped += 1
            continue
        text = alert.text()
        url = alert.original_url
        stmt = (
            insert(Document)
            .values(
                source_id=sid,
                source_key=f"alert:{alert.alert_id}"[:512],
                source_url=url,
                canonical_url=canonical_url(url) if url else None,
                retrieved_at=now,
                title=alert.caption[:2000],
                summary=alert.caption,
                original_text=text,
                language=LANGUAGES.get(alert.post_language or "", "en"),
                published_at=alert.occurred_at,
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
    return inserted, dropped


def inbox_dir() -> Path:
    return get_settings().raw_dir / SOURCE / "inbox"


def _ingest_file(path: Path, run: RunContext, seen: set[str]) -> dict[str, Any]:
    content = path.read_bytes()
    sha = sha256_bytes(content)
    entry: dict[str, Any] = {"name": path.name, "sha256": sha}
    if sha in seen or file_already_ingested(JOB, sha):
        entry["skipped"] = "already ingested"
        return entry
    digest = parse_digest(content.decode("utf-8"))
    snap = write_raw(SOURCE, run.id, path.name, content)
    run.raw_paths.append(str(snap.path))
    with session_factory()() as session, session.begin():
        inserted, dropped = upsert_alerts(
            session, source_id(session, SOURCE), digest, str(snap.path)
        )
    seen.add(sha)
    run.inserted += inserted
    entry |= {
        "watchlist": digest.watchlist,
        "window_start": digest.window_start.isoformat(),
        "window_end": digest.window_end.isoformat(),
        "alerts": len(digest.alerts),
        "inserted": inserted,
        "dropped_x_protest": dropped,
    }
    return entry


def run_inbox(files: list[Path] | None = None, *, remove: bool | None = None) -> int:
    """Ingest digest files (default: everything in the inbox). Inbox files are removed once
    stored; files given explicitly are left in place unless ``remove`` is set."""
    inbox = inbox_dir()
    explicit = files is not None
    paths = sorted(files) if files is not None else sorted(inbox.glob("*.txt"))
    remove = (not explicit) if remove is None else remove
    if not paths:
        _check_stalled()
        return 0
    failed: list[str] = []
    with ingest_run(JOB, source_slug=SOURCE, params={"files": []}) as run:
        seen: set[str] = set()
        for path in paths:
            try:
                entry = _ingest_file(path, run, seen)
            except (DataminrFormatError, UnicodeDecodeError) as exc:
                log.error("dataminr digest %s not parsed: %s", path.name, exc)
                failed.append(path.name)
                run.params["files"].append({"name": path.name, "error": str(exc)[:300]})
                if remove:
                    dest = inbox / "failed"
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), dest / path.name)
                continue
            run.params["files"].append(entry)
            if remove:
                path.unlink()
        windows = [
            (f["window_start"], f["window_end"]) for f in run.params["files"] if "window_end" in f
        ]
        run.params["gaps"] = _alert_gaps(windows)
        if failed:
            raise DataminrFormatError(
                f"{len(failed)} digest file(s) not parsed (moved to inbox/failed/): "
                + ", ".join(failed)
            )
    _check_stalled()
    return 0


# --------------------------------------------------------------------------- monitoring


def _recorded_windows(session: Session, since: dt.datetime) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for params in session.scalars(
        select(IngestRun.params).where(
            # An "error" run (one unparseable file) still stored its other files' windows.
            IngestRun.job == JOB,
            IngestRun.status.in_(("ok", "error")),
            IngestRun.started_at >= since,
        )
    ):
        for f in (params or {}).get("files", []):
            if "window_end" in f:
                out.append((f["window_start"], f["window_end"]))
    return out


def find_gaps(
    windows: list[tuple[dt.datetime, dt.datetime]],
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Holes between received digest windows (not before the first or after the last)."""
    gaps: list[tuple[dt.datetime, dt.datetime]] = []
    ordered = sorted(set(windows))
    if not ordered:
        return gaps
    covered_to = ordered[0][1]
    for start, end in ordered[1:]:
        if start > covered_to:
            gaps.append((covered_to, start))
        covered_to = max(covered_to, end)
    return gaps


def _alert_gaps(current: list[tuple[str, str]]) -> int:
    """Raise one ``feed_gap`` alert per missing span. Returns how many spans are missing."""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=GAP_LOOKBACK_DAYS)
    with session_factory()() as session, session.begin():
        raw = _recorded_windows(session, since) + current
        windows = [(dt.datetime.fromisoformat(s), dt.datetime.fromisoformat(e)) for s, e in raw]
        gaps = find_gaps(windows)
        for start, end in gaps:
            key = {"job": JOB, "gap_start": start.isoformat(), "gap_end": end.isoformat()}
            exists = session.scalar(
                select(Alert.id).where(Alert.rule == "feed_gap", Alert.linked_records.contains(key))
            )
            if exists:
                continue
            hst = ZoneInfo("Pacific/Honolulu")
            span = f"{start.astimezone(hst):%Y-%m-%d %H:%M} to {end.astimezone(hst):%H:%M} HST"
            session.add(
                Alert(
                    rule="feed_gap",
                    severity=1,
                    summary=(
                        f"Dataminr digest missing for {span} ({start:%H:%M}-{end:%H:%M} UTC). "
                        "Check that the email arrived in Gmail and that the connector saved it "
                        "to data/raw/dataminr/inbox/."
                    ),
                    linked_records=key,
                )
            )
            log.warning("dataminr digest gap: %s", span)
    return len(gaps)


def _check_stalled(now: dt.datetime | None = None) -> bool:
    """One ``feed_stalled`` alert when no digest window has ended in ``STALL_HOURS``."""
    now = now or dt.datetime.now(dt.UTC)
    with session_factory()() as session, session.begin():
        ends = [
            dt.datetime.fromisoformat(e)
            for _, e in _recorded_windows(session, now - dt.timedelta(days=GAP_LOOKBACK_DAYS))
        ]
        if not ends:
            return False
        newest = max(ends)
        if now - newest < dt.timedelta(hours=STALL_HOURS):
            return False
        key = {"job": JOB, "newest_window_end": newest.isoformat()}
        if session.scalar(
            select(Alert.id).where(Alert.rule == "feed_stalled", Alert.linked_records.contains(key))
        ):
            return False
        session.add(
            Alert(
                rule="feed_stalled",
                severity=1,
                summary=(
                    f"No new Dataminr digest for {STALL_HOURS}+ hours (newest window ended "
                    f"{newest:%Y-%m-%d %H:%M} UTC). Check the Gmail connector."
                ),
                linked_records=key,
            )
        )
    log.warning("dataminr digests stalled since %s", newest.isoformat())
    return True
