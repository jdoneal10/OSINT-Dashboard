"""Dates are calendar days where the report was published, not UTC days. All text is synthetic."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.config import get_settings
from app.db.models import Document, Source
from app.enrich import extract, persons
from app.ingest import articles, publication
from app.ingest.feeds import load_feeds


def utc(*parts: int) -> dt.datetime:
    return dt.datetime(*parts, tzinfo=dt.UTC)  # type: ignore[misc]


def _doc(published: dt.datetime | None, retrieved: dt.datetime | None = None) -> Any:
    return SimpleNamespace(
        id=1, published_at=published, retrieved_at=retrieved or utc(2026, 11, 23, 3, 0),
        source_url="https://example.org/x", title="T", original_text="Texto.", summary=None,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("slug", "published", "day"),
    [
        ("quadratin", utc(2026, 11, 22, 3, 0), "2026-11-21"),  # 21:00 in Mexico City
        ("quadratin", utc(2026, 11, 22, 18, 0), "2026-11-22"),
        ("lineadirecta", utc(2026, 11, 21, 6, 30), "2026-11-20"),  # 23:30 in Sinaloa
        ("zetatijuana", utc(2026, 11, 22, 7, 30), "2026-11-21"),  # 23:30 in Tijuana
        ("zetatijuana", utc(2026, 7, 22, 7, 30), "2026-07-22"),  # 00:30, daylight time
        ("dataminr", utc(2026, 11, 22, 3, 0), "2026-11-21"),
        ("dataminr", utc(2026, 11, 22, 0, 0), "2026-11-21"),  # a real time, not a bare date
        ("cbp-news", utc(2026, 11, 20, 0, 0), "2026-11-20"),  # a bare date
        ("quadratin", utc(2026, 11, 20, 0, 0), "2026-11-20"),  # a bare date from page metadata
        ("defensacom", utc(2026, 11, 20, 23, 50), "2026-11-20"),  # feed sends Madrid wall time
        ("not-registered", utc(2026, 11, 22, 3, 0), "2026-11-22"),
    ],
)
def test_published_day_is_local(slug: str, published: dt.datetime, day: str) -> None:
    assert publication.published_day(_doc(published), slug) == dt.date.fromisoformat(day)


def test_without_a_publication_time_the_retrieval_day_is_local() -> None:
    assert publication.published_day(_doc(None), "quadratin") == dt.date(2026, 11, 22)


def test_every_active_feed_declares_its_time_zone() -> None:
    feeds = load_feeds(get_settings().reference_dir / "feeds.yaml")
    missing = [
        f.slug for f in feeds if f.status == "active" and "timezone" not in f.model_fields_set
    ]
    assert not missing


def test_the_model_gets_the_local_day_weekday_and_time() -> None:
    source = cast(Source, SimpleNamespace(name="Synthetic", slug="quadratin"))
    shown = extract.build_user(cast(Document, _doc(utc(2026, 11, 23, 3, 0))), source)
    assert "PUBLISHED: 2026-11-22 Sunday (domingo), 21:00 local time" in shown
    assert "2026-11-23" not in shown
    assert len([x for x in shown.splitlines() if x.startswith(("PUBLISHED", "DAYS"))]) == 1


def test_a_bare_date_gets_no_made_up_time() -> None:
    source = cast(Source, SimpleNamespace(name="Synthetic", slug="cbp-news"))
    shown = extract.build_user(cast(Document, _doc(utc(2026, 11, 20, 0, 0))), source)
    assert "PUBLISHED: 2026-11-20 Friday (viernes)\n" in shown


def test_person_claims_are_dated_by_the_local_day() -> None:
    source = cast(Source, SimpleNamespace(id=1, slug="quadratin", reliability="B"))
    doc = cast(Document, _doc(utc(2026, 11, 22, 3, 0)))
    cited = persons.citation_for(doc, source, None, model="m", prompt_version="v")
    assert cited.reported_on == dt.date(2026, 11, 21)


def test_page_time_replaces_the_time_gdelt_saw_the_article() -> None:
    page = (
        '<html><head><meta property="article:published_time" '
        'content="2026-11-20T21:56:38-06:00"></head></html>'
    )
    seen = utc(2026, 11, 21, 6, 45)
    assert publication.page_time(page, seen) == utc(2026, 11, 21, 3, 56, 38)
    # A date alone, a time without an offset, or a time after GDELT saw it is not used.
    for bad in ("2026-11-20", "2026-11-20T21:56:38", "2026-11-22T09:00:00-06:00"):
        assert publication.page_time(page.replace("2026-11-20T21:56:38-06:00", bad), seen) == seen


def test_page_time_reads_json_ld_when_there_is_no_meta_tag() -> None:
    page = '<script>{"@type":"NewsArticle","datePublished":"2026-11-19T20:58:33-0000"}</script>'
    assert publication.page_time(page, utc(2026, 11, 19, 23, 30)) == utc(2026, 11, 19, 20, 58, 33)


def test_a_us_release_date_is_read_month_first() -> None:
    page = "<div>Release Date</div> <div><time>Tue, 11/10/2026</time></div>"
    assert publication.release_date(page) == utc(2026, 11, 10)
    # Only with the weekday it claims: otherwise it is some other date format.
    assert publication.release_date(page.replace("Tue", "Sun")) is None
    assert publication.release_date(page.replace("11/10", "13/45")) is None
    assert publication.release_date("<p>No date here</p>") is None


def test_a_fetched_release_is_not_dated_day_first() -> None:
    page = (
        "<html><body><article><div>Release Date</div><div>Tue, 11/10/2026</div>"
        "<p>Synthetic officers seized a synthetic load at a synthetic port of entry.</p>"
        "</article></body></html>"
    )
    response = SimpleNamespace(
        status_code=200, text=page, content=page.encode(), headers={"content-type": "text/html"}
    )
    client = cast(Any, SimpleNamespace(get=lambda _url: response))
    fetched = articles.fetch_article(client, "https://example.org/release")
    assert fetched is not None
    assert fetched.published == utc(2026, 11, 10)
