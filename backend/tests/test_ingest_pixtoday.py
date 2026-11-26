"""Pixtoday.net event exports: parsing, the rule-4 drop, one document per X post, overlap
between exports, and one independent source per relayed post (ADR 0010). Fixtures are
synthetic; see tests/fixtures/pixtoday/README.md."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, IngestRun, Source
from app.enrich.dedupe import independent_sources, origin_key
from app.ingest import pixtoday
from app.ingest.pixtoday import PixFormatError, parse_export, posted_at

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pixtoday"
FIRST = FIXTURES / "PiX_MEX_ActiveCartels_Events_20261112.csv"
LATER = FIXTURES / "PiX_MEX_ActiveCartels_Events_20261113.csv"


def test_parse_groups_rows_by_post_and_drops_rule_4_and_uncited_rows() -> None:
    export = parse_export(FIRST.read_text(encoding="utf-8"))
    assert (export.rows, export.dropped_government, export.dropped_no_source) == (6, 1, 1)
    drone, mining, arson = export.posts
    assert drone.status_id == "2118002830341046272"
    assert drone.posted_at == dt.datetime(2026, 11, 4, 15, 30, tzinfo=dt.UTC)
    assert drone.organizations == ["CJNG"]
    # One post mapped to two locations is one record.
    assert mining.locations == [(24.8001, -107.4001), (24.9001, -107.5001)]
    assert mining.organizations == ["Sinaloa (Mayitos)"]  # "Unknown" is not an organization
    assert mining.categories == ["Security Operations", "Seizure"]
    # No PiX date: the day the post went up. A twitter.com link keeps no query string.
    assert arson.event_dates == [dt.date(2026, 11, 9)]
    assert arson.url == "https://twitter.com/Example_Local/status/2119761921438646272"
    text = drone.text()
    assert text.startswith("Armed men attacked")
    assert "PiX record: event date 2026-11-04; organizations (PiX attribution) CJNG" in text


def test_snowflake_time() -> None:
    assert posted_at("2120803786552246272") == dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.UTC)


def test_not_a_pix_export() -> None:
    with pytest.raises(PixFormatError, match="missing columns"):
        parse_export("a,b\n1,2\n")


def test_import_is_idempotent_and_a_later_export_adds_only_new_posts(
    seeded: Session, raw_dir: Path
) -> None:
    assert pixtoday.run_file(FIRST) == 0
    assert pixtoday.run_file(FIRST) == 0  # same file again: skipped
    assert pixtoday.run_file(LATER) == 0  # overlaps: one new post
    sid = seeded.scalars(select(Source.id).where(Source.slug == "pixtoday")).one()
    docs = list(seeded.scalars(select(Document).where(Document.source_id == sid)))
    assert len(docs) == 4
    by_key = {d.source_key: d for d in docs}
    mining = by_key["x:2118163891614646272"]
    assert mining.source_url == "https://x.com/example_outlet/status/2118163891614646272"
    assert (mining.pipeline_status, mining.language, mining.text_policy) == ("new", "en", "full")
    assert by_key["x:2119761921438646272"].language == "es"
    assert not any("Federal troops" in (d.original_text or "") for d in docs)
    runs = list(seeded.scalars(select(IngestRun).where(IngestRun.job == "pixtoday")))
    assert [r.rows_inserted for r in sorted(runs, key=lambda r: r.id)] == [3, 0, 1]
    first = min(runs, key=lambda r: r.id)
    assert first.params["files"][0]["dropped_government_operations"] == 1
    assert (raw_dir / "pixtoday").is_dir()


def test_the_same_post_relayed_by_two_sources_counts_once() -> None:
    post = "https://x.com/Example_Reporter/status/2118002830341046272"
    assert origin_key(post) == origin_key(
        "https://twitter.com/example_reporter/status/2118002830341046272"
    )
    pix, dataminr, outlet = 1, 2, 3
    # PiX and Dataminr relay one post; an outlet's own article is independent of it.
    docs = [(pix, post), (dataminr, post), (outlet, "https://example.com/nota")]
    assert independent_sources(docs, set()) == 2
    # Record-level sources (ACLED) stay independent.
    assert independent_sources(docs, {4}) == 3
    # Documents without a URL still count by source.
    assert independent_sources([(pix, None), (dataminr, None)], set()) == 2
