from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Alert, Document, IngestRun, Source
from app.ingest import feeds as feed_registry
from app.ingest import news
from app.ingest.articles import canonical_url
from app.ingest.feeds import load_feeds
from app.ingest.http import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "news"
ROBOTS = "User-agent: *\nDisallow: /private/\n"


@pytest.fixture(autouse=True)
def _test_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feed_registry, "feeds_path", lambda: FIX / "feeds.yaml")


class Site:
    """Mock web: robots, feeds, listing, articles and GDELT."""

    def __init__(self) -> None:
        self.full_feed = (FIX / "full-feed.xml").read_bytes()
        self.calls: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append(url)
        host, path = req.url.host, req.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        routes = {
            ("full.example.org", "/feed/"): self.full_feed,
            ("press.example.org", "/rss"): (FIX / "press-feed.xml").read_bytes(),
            ("press.example.org", "/pr/synthetic-indictment"): (FIX / "article.html").read_bytes(),
            ("list.example.org", "/newsroom/all"): (FIX / "listing.html").read_bytes(),
            ("pay.example.org", "/rss.xml"): (FIX / "pay-feed.xml").read_bytes(),
            ("api.gdeltproject.org", "/api/v2/doc/doc"): (FIX / "gdelt.json").read_bytes(),
        }
        if host in ("list.example.org", "www.gd.example.org") and path not in ("/newsroom/all",):
            return httpx.Response(
                200,
                content=(FIX / "article.html").read_bytes(),
                headers={"content-type": "text/html"},
            )
        body = routes.get((host, path))
        if body is None:
            return httpx.Response(404)
        ctype = "application/json" if path.endswith("/doc") else "text/html"
        return httpx.Response(200, content=body, headers={"content-type": ctype})

    def client(self) -> PoliteClient:
        return PoliteClient(
            transport=httpx.MockTransport(self.handler), min_interval=0, sleep=lambda _s: None
        )


def _docs(session: Session, slug: str) -> list[Document]:
    session.expire_all()
    return list(
        session.scalars(
            select(Document)
            .join(Source, Source.id == Document.source_id)
            .where(Source.slug == slug)
        )
    )


def _run(site: Site, *slugs: str) -> None:
    with site.client() as client:
        news.run_news(list(slugs) or None, client=client)


def test_repository_feeds_file_validates() -> None:
    feeds = load_feeds(get_settings().reference_dir / "feeds.yaml")
    assert {f.slug for f in feeds} >= {"doj", "insightcrime", "proceso", "milenio"}
    assert all(f.sources for f in feeds)


def test_canonical_url_drops_tracking_and_www() -> None:
    assert (
        canonical_url("https://WWW.Example.org/a/b?utm_source=rss&id=7#top")
        == "https://example.org/a/b?id=7"
    )


@pytest.mark.usefixtures("seeded")
def test_sync_sources_and_pending_feeds_skipped(session: Session) -> None:
    site = Site()
    _run(site)
    grades = dict(session.execute(select(Source.slug, Source.reliability)).all())
    assert grades["test-press"] == "A"
    assert grades["test-fulltext"] == "B"
    assert not any("pending.example.org" in c for c in site.calls)


def test_rss_with_full_content_needs_no_page_fetch(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(news, "MIN_FEED_TEXT_CHARS", 50)  # fixture content counts as full text
    site = Site()
    _run(site, "test-fulltext")
    (doc,) = _docs(seeded, "test-fulltext")
    assert "enfrentamiento entre grupos armados" in (doc.original_text or "")
    assert doc.canonical_url == "https://full.example.org/2026/11/enfrentamiento"
    assert (doc.language, doc.pipeline_status, doc.text_policy) == ("es", "new", "full")
    assert not any("/2026/11/enfrentamiento" in c for c in site.calls)


def test_summary_rss_fetches_article_and_respects_robots(seeded: Session) -> None:
    site = Site()
    _run(site, "test-press")
    docs = {d.source_key.rsplit("/", 1)[-1]: d for d in _docs(seeded, "test-press")}
    assert "synthetic indictment against members" in (
        docs["synthetic-indictment"].original_text or ""
    )
    assert docs["synthetic-indictment"].raw_path
    blocked = docs["blocked"]
    assert blocked.original_text is None  # robots.txt disallows /private/
    assert blocked.summary == "Teaser for a robots-blocked page."
    assert blocked.pipeline_status == "new"  # title + teaser still go to the pipeline
    assert not any("/private/blocked" in c for c in site.calls)


def test_rerun_is_idempotent_and_does_not_refetch(seeded: Session) -> None:
    site = Site()
    _run(site, "test-press")
    first = {d.id for d in _docs(seeded, "test-press")}
    _run(site, "test-press")
    assert {d.id for d in _docs(seeded, "test-press")} == first
    assert sum("/pr/synthetic-indictment" in c for c in site.calls) == 1


def test_changed_text_resets_pipeline_status(seeded: Session) -> None:
    site = Site()
    _run(site, "test-fulltext")
    (doc,) = _docs(seeded, "test-fulltext")
    doc.pipeline_status = "extracted"
    seeded.commit()

    _run(site, "test-fulltext")  # unchanged -> stays extracted (and is skipped as known)
    assert _docs(seeded, "test-fulltext")[0].pipeline_status == "extracted"

    with session_scope(seeded):
        doc = _docs(seeded, "test-fulltext")[0]
        doc.original_text = None  # force a re-fetch path for the changed content
    site.full_feed = site.full_feed.replace(b"tres muertos", b"cuatro muertos")
    _run(site, "test-fulltext")
    doc = _docs(seeded, "test-fulltext")[0]
    assert "cuatro muertos" in (doc.original_text or "")
    assert doc.pipeline_status == "new"


class session_scope:  # noqa: N801 — tiny helper context manager
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *exc: object) -> None:
        self.session.commit()


def test_listing_uses_link_pattern(seeded: Session) -> None:
    site = Site()
    _run(site, "test-listing")
    urls = sorted(d.source_url or "" for d in _docs(seeded, "test-listing"))
    assert urls == [
        "https://list.example.org/newsroom/local-media-release/officers-seize-synthetic-fentanyl",
        "https://list.example.org/newsroom/national-media-release/synthetic-national-release",
    ]


def test_gdelt_filters_domain_and_tracks_watermark(seeded: Session) -> None:
    site = Site()
    _run(site, "test-gdelt")
    docs = _docs(seeded, "test-gdelt")
    assert [d.source_url for d in docs] == ["https://www.gd.example.org/nacional/sintetico-1"]
    gdelt_call = next(c for c in site.calls if "gdeltproject" in c)
    assert "domain%3Agd.example.org" in gdelt_call
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == "news-test-gdelt")).one()
    assert run.params["until"]

    _run(site, "test-gdelt")
    second = [c for c in site.calls if "gdeltproject" in c][-1]
    assert f"startdatetime={run.params['until'][:4]}" in second  # resumes from last run


def _gdelt_refusing(site: Site) -> None:
    original = site.handler

    def refuse(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.gdeltproject.org":
            site.calls.append(str(req.url))
            return httpx.Response(429)
        return original(req)

    site.handler = refuse  # type: ignore[method-assign]


def _gdelt_runs(session: Session) -> list[tuple[str, str | None]]:
    session.expire_all()
    rows = session.execute(
        select(IngestRun.status, IngestRun.error)
        .where(IngestRun.job == "news-test-gdelt")
        .order_by(IngestRun.id)
    ).all()
    return [(r.status, r.error) for r in rows]


def test_gdelt_429_without_prior_success_is_an_error(seeded: Session) -> None:
    site = Site()
    _gdelt_refusing(site)
    _run(site, "test-gdelt")
    ((status, error),) = _gdelt_runs(seeded)
    assert status == "error"
    assert error is not None
    assert "429" in error


def test_gdelt_429_within_lookback_is_deferred_and_alerts_once_per_streak(
    seeded: Session,
) -> None:
    site = Site()
    _run(site, "test-gdelt")  # success sets the watermark
    _gdelt_refusing(site)
    for _ in range(3):
        _run(site, "test-gdelt")
    statuses = [s for s, _ in _gdelt_runs(seeded)]
    assert statuses == ["ok", "deferred", "deferred", "deferred"]
    alerts = seeded.scalars(select(Alert).where(Alert.rule == "feed_stalled")).all()
    assert len(alerts) == 1  # at the second miss, not again at the third
    assert alerts[0].linked_records == {"job": "news-test-gdelt", "misses": 2}

    site.handler = Site().handler  # type: ignore[method-assign]
    _run(site, "test-gdelt")  # recovery resumes from the last success's watermark
    _gdelt_refusing(site)
    _run(site, "test-gdelt")
    _run(site, "test-gdelt")
    assert len(seeded.scalars(select(Alert).where(Alert.rule == "feed_stalled")).all()) == 2


def test_gdelt_429_beyond_lookback_is_an_error(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = Site()
    _run(site, "test-gdelt")
    # the next run (6 h on) would start past a 1-hour lookback, so the gap is not covered
    monkeypatch.setattr(news, "GDELT_LOOKBACK", dt.timedelta(hours=1))
    _gdelt_refusing(site)
    _run(site, "test-gdelt")
    assert [s for s, _ in _gdelt_runs(seeded)] == ["ok", "error"]


def test_summary_policy_never_fetches_pages(seeded: Session) -> None:
    site = Site()
    _run(site, "test-paywall")
    (doc,) = _docs(seeded, "test-paywall")
    assert (doc.text_policy, doc.original_text, doc.summary) == (
        "summary",
        None,
        "Avance sintético.",
    )
    assert not any("/nota/1" in c for c in site.calls)


def test_one_failing_feed_does_not_stop_others(seeded: Session) -> None:
    site = Site()
    original = site.handler

    def flaky(req: httpx.Request) -> httpx.Response:
        if req.url.host == "press.example.org" and req.url.path == "/rss":
            return httpx.Response(500)
        return original(req)

    site.handler = flaky  # type: ignore[method-assign]
    _run(site, "test-press", "test-fulltext")
    assert _docs(seeded, "test-fulltext")
    statuses = dict(
        seeded.execute(
            select(IngestRun.job, IngestRun.status).where(IngestRun.job.like("news-%"))
        ).all()
    )
    assert statuses == {"news-test-press": "error", "news-test-fulltext": "ok"}


def test_teaser_only_feed_content_falls_back_to_article_page(
    seeded: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(news, "MIN_FEED_TEXT_CHARS", 10_000)  # fixture content counts as a teaser
    site = Site()
    original = site.handler

    def with_article(req: httpx.Request) -> httpx.Response:
        if req.url.host == "full.example.org" and req.url.path.startswith("/2026/"):
            site.calls.append(str(req.url))
            return httpx.Response(
                200,
                content=(FIX / "article.html").read_bytes(),
                headers={"content-type": "text/html"},
            )
        return original(req)

    site.handler = with_article  # type: ignore[method-assign]
    _run(site, "test-fulltext")
    (doc,) = _docs(seeded, "test-fulltext")
    assert "synthetic indictment against members" in (doc.original_text or "")
    assert any("/2026/11/enfrentamiento" in c for c in site.calls)


def test_listing_reads_links_from_a_javascript_listing() -> None:
    """gob.mx archives answer with JavaScript; cards come from ``.append("...")`` strings."""
    content = (FIX / "gobmx-listing.js").read_bytes()
    entries = news.parse_listing(
        content, "https://www.gob.mx/agencia/es/archivo/prensa", r"^/agencia/prensa/[a-z0-9-]+$"
    )
    assert [e.url for e in entries] == [
        "https://www.gob.mx/agencia/prensa/agencia-sintetica-asegura-dron-con-explosivos?idiom=es",
        "https://www.gob.mx/agencia/prensa/informe-sintetico-de-acciones-relevantes?idiom=es",
    ]  # the other agency's card and the pagination link are left out
    assert entries[0].title == "AGENCIA SINTÉTICA ASEGURA DRON CON EXPLOSIVOS EN MICHOACÁN"
    # 15:46 in Mexico City (UTC-6, no daylight saving) is 21:46 UTC.
    assert entries[0].published == dt.datetime(2026, 11, 20, 21, 46, tzinfo=dt.UTC)
