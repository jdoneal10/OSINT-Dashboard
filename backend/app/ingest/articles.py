"""Shared article handling for news ingesters: canonical URLs, polite full-text fetch,
text extraction, and the idempotent ``documents`` upsert.

Text policy (ADR 0004): ``full`` fetches the article page (robots.txt checked on every fetch
by ``PoliteClient``); ``summary`` keeps only title, teaser and link. Article HTML is kept in
data/raw/ (never committed). A document goes back to ``pipeline_status='new'`` only when its
text actually changes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import trafilatura
from lxml import html as lxml_html
from sqlalchemy import Boolean, case, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Document
from app.ingest.feeds import Feed
from app.ingest.http import PoliteClient, RobotsDisallowedError
from app.ingest.raw import sha256_bytes, write_raw

log = logging.getLogger(__name__)

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|_ga$|ref$|rss$)", re.IGNORECASE)
MAX_TEXT_CHARS = 200_000  # far above any article; guards against runaway pages


def canonical_url(url: str) -> str:
    """Lowercase scheme/host, drop fragment and tracking params, keep the path as published."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    netloc = parts.netloc.lower().removeprefix("www.") if parts.netloc else parts.netloc
    return urlunsplit((parts.scheme.lower() or "https", netloc, parts.path, query, ""))


def source_key(url: str) -> str:
    canon = canonical_url(url)
    return canon if len(canon) <= 512 else hashlib.sha256(canon.encode()).hexdigest()


def html_to_text(fragment: str) -> str:
    """Plain text from an HTML fragment (e.g. RSS content:encoded)."""
    if not fragment.strip():
        return ""
    extracted = trafilatura.extract(
        f"<html><body>{fragment}</body></html>", include_comments=False, favor_recall=True
    )
    if extracted:
        return extracted
    try:
        return " ".join(lxml_html.fromstring(fragment).text_content().split())
    except (ValueError, TypeError):
        return ""


@dataclass
class FetchedArticle:
    html: bytes
    text: str | None
    title: str | None
    published: dt.datetime | None
    language: str | None


def _parse_date(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def fetch_article(client: PoliteClient, url: str) -> FetchedArticle | None:
    """GET an article page (robots.txt enforced) and extract its main text."""
    try:
        resp = client.get(url)
    except RobotsDisallowedError:
        log.info("robots.txt disallows %s; skipped", url)
        return None
    except httpx.HTTPError as exc:
        log.warning("fetch failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200 or "html" not in resp.headers.get("content-type", "html"):
        log.warning("fetch %s -> HTTP %d", url, resp.status_code)
        return None
    text = trafilatura.extract(resp.text, include_comments=False, favor_precision=True)
    meta = trafilatura.extract_metadata(resp.text)
    return FetchedArticle(
        html=resp.content,
        text=text[:MAX_TEXT_CHARS] if text else None,
        title=meta.title if meta else None,
        published=_parse_date(meta.date) if meta else None,
        language=None,
    )


def known_keys(session: Session, source_id: int, keys: list[str]) -> set[str]:
    """Source keys already stored with text (skip re-fetching their pages)."""
    if not keys:
        return set()
    return set(
        session.scalars(
            select(Document.source_key).where(
                Document.source_id == source_id,
                Document.source_key.in_(keys),
                Document.original_text.is_not(None) | (Document.text_policy == "summary"),
            )
        )
    )


@dataclass
class UpsertResult:
    id: int
    inserted: bool
    changed: bool


def upsert_document(
    session: Session,
    *,
    source_id: int,
    feed: Feed,
    url: str,
    title: str | None,
    summary: str | None,
    text: str | None,
    published: dt.datetime | None,
    raw_path: str | None,
) -> UpsertResult:
    """Insert or update by (source_id, source_key); reset the pipeline only on text change."""
    body = text if feed.text == "full" else None
    content = "\n".join(x for x in (title, summary, body) if x)
    digest = hashlib.sha256(content.encode()).hexdigest() if content else None
    values = {
        "source_id": source_id,
        "source_key": source_key(url),
        "source_url": url,
        "canonical_url": canonical_url(url),
        "retrieved_at": dt.datetime.now(dt.UTC),
        "title": (title or "")[:2000] or None,
        "summary": summary,
        "original_text": body,
        "language": feed.language,
        "published_at": published,
        "raw_path": raw_path,
        "content_sha256": digest,
        "text_policy": feed.text,
        "pipeline_status": "new" if content else "skipped",
    }
    base = insert(Document).values(**values)
    excluded = base.excluded
    changed = Document.content_sha256.is_distinct_from(excluded.content_sha256)
    stmt = base.on_conflict_do_update(
        constraint="uq_documents_source_key",
        set_={
            "title": func.coalesce(excluded.title, Document.title),
            "summary": func.coalesce(excluded.summary, Document.summary),
            "original_text": func.coalesce(excluded.original_text, Document.original_text),
            "published_at": func.coalesce(excluded.published_at, Document.published_at),
            "raw_path": func.coalesce(excluded.raw_path, Document.raw_path),
            "retrieved_at": excluded.retrieved_at,
            "content_sha256": func.coalesce(excluded.content_sha256, Document.content_sha256),
            "pipeline_status": case(
                (changed & excluded.content_sha256.is_not(None), "new"),
                else_=Document.pipeline_status,
            ),
            "updated_at": func.now(),
        },
    ).returning(
        Document.id,
        literal_column("(xmax = 0)", Boolean),
        literal_column("documents.pipeline_status = 'new'", Boolean),
    )
    doc_id, inserted, is_new = session.execute(stmt).one()
    return UpsertResult(id=doc_id, inserted=bool(inserted), changed=bool(is_new) and not inserted)


def store_raw_html(source: str, run_id: int, url: str, content: bytes) -> str:
    name = sha256_bytes(canonical_url(url).encode())[:16] + ".html"
    return str(write_raw(source, run_id, name, content).path)
