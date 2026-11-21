"""News / press-release ingester driven by ``feeds.yaml`` (ADR 0004).

Discovery per feed: RSS (``feedparser``), an HTML listing page (``link_pattern``), or GDELT
DOC 2.0 queries restricted to the feed's domain. Articles land in ``documents`` with
``pipeline_status='new'`` for the enrichment pipeline. Each feed is its own ``ingest_runs``
row (job ``news-<slug>``), so one failing outlet never blocks the rest.

    python -m app.ingest news                 # every active feed
    python -m app.ingest news --feed doj      # one feed
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import feedparser
from lxml import html as lxml_html

from app.db.models import Alert
from app.db.session import session_factory
from app.ingest import feeds as feed_registry
from app.ingest.articles import (
    fetch_article,
    html_to_text,
    known_keys,
    source_key,
    store_raw_html,
    upsert_document,
)
from app.ingest.feeds import Feed
from app.ingest.http import PoliteClient
from app.ingest.raw import write_raw
from app.ingest.runs import (
    DeferredRun,
    RunContext,
    ingest_run,
    last_successful_params,
    misses_since_success,
    source_id,
)

log = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MEXICO_CITY = ZoneInfo("America/Mexico_City")
GDELT_MIN_INTERVAL = 20.0  # GDELT asks for one request per 5 s; it still answered 429 at ~15 s
# GDELT's 429s outlast short retries (observed 2026-11-12/13): wait 30 s, 1, 2, then 4 min.
GDELT_BACKOFF_INITIAL = 30.0
GDELT_LOOKBACK = dt.timedelta(days=3)  # first run / gap cap
# The worker queries GDELT every 6 hours; a refused run is deferred (not an error) while the
# next run's window would still reach back to the last success.
GDELT_SCHEDULE_INTERVAL = dt.timedelta(hours=6)
# Alert once a feed has missed this many runs in a row (owner decision 2026-11-15).
STALL_ALERT_MISSES = 2
# Spanish + English terms for organized-crime reporting; the local relevance filter refines.
GDELT_TERMS = (
    '(cártel OR cartel OR narco OR narcotráfico OR "crimen organizado" OR sicarios OR '
    'fentanilo OR fentanyl OR decomiso OR aseguramiento OR huachicol OR "fosa clandestina" '
    'OR homicidios OR "Guardia Nacional" OR trafficking)'
)
MAX_ENTRIES_PER_RUN = 200
# Some feeds put only a teaser in content:encoded; below this, fetch the article page instead.
MIN_FEED_TEXT_CHARS = 800


@dataclass
class Entry:
    url: str
    title: str | None = None
    summary: str | None = None
    content_html: str | None = None
    published: dt.datetime | None = None


# --------------------------------------------------------------------------- discovery


def _struct_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    year, month, day, hour, minute, second = value[:6]
    return dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC)


def parse_rss(content: bytes) -> list[Entry]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        link = e.get("link")
        if not link:
            continue
        content_html = e["content"][0].get("value") if e.get("content") else None
        out.append(
            Entry(
                url=link,
                title=e.get("title"),
                summary=html_to_text(e.get("summary", "")) or None,
                content_html=content_html,
                published=_struct_time(e.get("published_parsed") or e.get("updated_parsed")),
            )
        )
    return out


# gob.mx archive listings answer with JavaScript (text/javascript): the article markup sits
# in escaped string literals passed to ``$("#prensa").append("...")``. Such literals are read
# wherever they appear, in a script response or an inline <script>.
_JS_APPEND = re.compile(r'\.append\(\s*"((?:[^"\\]|\\.)*)"\s*\)', re.S)


def _script_fragments(text: str) -> list[Any]:
    """HTML fragments that scripts build with ``.append("...")`` string literals."""
    out = []
    for literal in _JS_APPEND.findall(text):
        try:
            markup = json.loads(f'"{literal}"')
        except ValueError:
            continue
        if "<a" in markup:
            out.append(lxml_html.fragment_fromstring(markup, create_parent="div"))
    return out


def parse_listing(content: bytes, base_url: str, link_pattern: str) -> list[Entry]:
    pattern = re.compile(link_pattern)
    host = urlsplit(base_url).netloc.lower()
    text = content.decode("utf-8", errors="replace")
    fragments = _script_fragments(text) if ".append(" in text else []
    roots = [*fragments] if fragments and not text.lstrip().startswith("<") else []
    if not roots:
        roots = [lxml_html.fromstring(content), *fragments]
    seen: dict[str, Entry] = {}
    for root in roots:
        for a in root.iter("a"):
            href = a.get("href")
            if not href:
                continue
            url = urljoin(base_url, href)
            parts = urlsplit(url)
            # Only the agency's own articles: same host, matching path.
            if parts.netloc.lower() == host and pattern.search(parts.path) and url not in seen:
                title = a.get("aria-label") or " ".join(a.text_content().split()) or None
                seen[url] = Entry(url=url, title=title, published=_listed_time(a))
    return list(seen.values())


def _listed_time(a: Any) -> dt.datetime | None:
    """``<time datetime="YYYY-MM-DD HH:MM:SS">`` in the link's ``<article>`` card (gob.mx
    listings; Mexico City time, UTC-6 with no daylight saving since 2022)."""
    card = next((el for el in a.iterancestors() if el.tag == "article"), None)
    stamp = card.find(".//time") if card is not None else None
    raw = stamp.get("datetime") if stamp is not None else None
    if not raw:
        return None
    try:
        naive = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive.astimezone(dt.UTC)
    return naive.replace(tzinfo=MEXICO_CITY).astimezone(dt.UTC)


def parse_gdelt(payload: dict[str, Any], domain: str) -> list[Entry]:
    out = []
    bare = domain.removeprefix("www.")
    for art in payload.get("articles") or []:
        url = art.get("url")
        if not url or urlsplit(url).netloc.removeprefix("www.") != bare:
            continue  # GDELT domain matching is loose; keep only the registered domain
        seen = art.get("seendate")
        published = (
            dt.datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC) if seen else None
        )
        out.append(Entry(url=url, title=art.get("title"), published=published))
    return out


def gdelt_params(domain: str, start: dt.datetime, end: dt.datetime) -> dict[str, str]:
    return {
        "query": f"{GDELT_TERMS} domain:{domain.removeprefix('www.')}",
        "mode": "ArtList",
        "format": "json",
        "maxrecords": "250",
        "sort": "DateDesc",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }


def discover(
    feed: Feed, client: PoliteClient, gdelt_client: PoliteClient, run: RunContext
) -> list[Entry]:
    if feed.discovery == "rss":
        resp = client.get(str(feed.url))
        resp.raise_for_status()
        run.raw_paths.append(str(write_raw(feed.slug, run.id, "feed.xml", resp.content).path))
        return parse_rss(resp.content)
    if feed.discovery == "listing":
        resp = client.get(str(feed.url))
        resp.raise_for_status()
        run.raw_paths.append(str(write_raw(feed.slug, run.id, "listing.html", resp.content).path))
        return parse_listing(resp.content, str(feed.url), feed.link_pattern or "")
    # gdelt: from the last successful run's end (capped), to now
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    last = last_successful_params(f"news-{feed.slug}") or {}
    start = now - GDELT_LOOKBACK
    if last.get("until"):
        start = max(start, dt.datetime.fromisoformat(last["until"]) - dt.timedelta(hours=1))
    run.params["until"] = now.isoformat()
    resp = gdelt_client.get(GDELT_URL, params=gdelt_params(feed.domain, start, now), crawl=False)
    if resp.status_code == 429 and _next_run_covers(last, now):
        raise DeferredRun(
            f"GDELT 429 after retries; next run resumes from {last['until']} (within lookback)"
        )
    resp.raise_for_status()
    run.raw_paths.append(str(write_raw(feed.slug, run.id, "gdelt.json", resp.content).path))
    if not resp.content.strip():
        return []
    try:
        payload = resp.json()
    except ValueError:  # GDELT answers malformed queries with plain-text errors
        raise RuntimeError(f"GDELT returned non-JSON: {resp.text[:200]!r}") from None
    return parse_gdelt(payload, feed.domain)


def _next_run_covers(last: dict[str, Any], now: dt.datetime) -> bool:
    """True if the next scheduled run would still reach back to the last success."""
    until = last.get("until")
    if not until:
        return False
    gap = now + GDELT_SCHEDULE_INTERVAL - dt.datetime.fromisoformat(until)
    return gap <= GDELT_LOOKBACK


def _alert_if_stalled(feed: Feed) -> None:
    """One alert per streak, when a feed reaches ``STALL_ALERT_MISSES`` deferred or failed
    runs in a row."""
    job = f"news-{feed.slug}"
    misses = misses_since_success(job)
    if misses != STALL_ALERT_MISSES:
        return
    with session_factory()() as session, session.begin():
        session.add(
            Alert(
                rule="feed_stalled",
                severity=1,
                summary=(
                    f"{feed.name} ({job}) has missed {misses} runs in a row. For GDELT feeds "
                    "no articles are lost while the lookback covers the gap; check the run "
                    "errors if it continues."
                ),
                linked_records={"job": job, "misses": misses},
            )
        )
    log.warning("feed %s stalled: %d misses in a row", feed.slug, misses)


# --------------------------------------------------------------------------- ingest


def ingest_feed(
    feed: Feed, client: PoliteClient, gdelt_client: PoliteClient | None = None
) -> RunContext:
    gdelt_client = gdelt_client or client
    with ingest_run(f"news-{feed.slug}", source_slug=feed.slug, params={"feed": feed.slug}) as run:
        entries = discover(feed, client, gdelt_client, run)[:MAX_ENTRIES_PER_RUN]
        run.params["discovered"] = len(entries)
        with session_factory()() as session:
            sid = source_id(session, feed.slug)
            have = known_keys(session, sid, [source_key(e.url) for e in entries])
        fetched = skipped = 0
        for entry in entries:
            if source_key(entry.url) in have:
                skipped += 1
                continue
            text, raw_path = None, None
            title, published = entry.title, entry.published
            if feed.text == "full":
                if entry.content_html:
                    text = html_to_text(entry.content_html) or None
                if not text or len(text) < MIN_FEED_TEXT_CHARS:
                    article = fetch_article(client, entry.url)
                    if article is not None and article.text:
                        fetched += 1
                        raw_path = store_raw_html(feed.slug, run.id, entry.url, article.html)
                        text = article.text
                        title = title or article.title
                        published = published or article.published
            with session_factory()() as session, session.begin():
                result = upsert_document(
                    session,
                    source_id=sid,
                    feed=feed,
                    url=entry.url,
                    title=title,
                    summary=entry.summary,
                    text=text,
                    published=published,
                    raw_path=raw_path,
                )
            if result.inserted:
                run.inserted += 1
            else:
                run.updated += 1
        run.params |= {"fetched_pages": fetched, "already_stored": skipped}
    return run


def run_news(slugs: list[str] | None = None, client: PoliteClient | None = None) -> int:
    feeds = [f for f in feed_registry.active() if not slugs or f.slug in slugs]
    if slugs and len(feeds) != len(set(slugs)):
        known = {f.slug for f in feed_registry.load_feeds()}
        raise ValueError(
            f"unknown or inactive feed(s): {sorted(set(slugs) - {f.slug for f in feeds})}"
            f"; registered: {sorted(known)}"
        )
    with session_factory()() as session, session.begin():
        feed_registry.sync_sources(session)
    owns = client is None
    client = client or PoliteClient(min_interval=1.0, timeout=30)
    gdelt_client = (
        client
        if not owns
        else PoliteClient(
            min_interval=GDELT_MIN_INTERVAL, timeout=60, backoff_initial=GDELT_BACKOFF_INITIAL
        )
    )
    failures = 0
    try:
        for feed in feeds:
            try:
                ingest_feed(feed, client, gdelt_client)
            except Exception:
                failures += 1
                log.exception("feed %s failed (recorded in ingest_runs)", feed.slug)
            _alert_if_stalled(feed)
    finally:
        if owns:
            client.close()
            gdelt_client.close()
    return 1 if failures == len(feeds) and feeds else 0
