"""Dataminr First Alert digests: parsing, the X protest rule, inbox handling and gap alerts
(ADR 0012). Fixtures are synthetic; see tests/fixtures/dataminr/README.md."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, Document, IngestRun, Source
from app.ingest import dataminr
from app.ingest.dataminr import DataminrFormatError, find_gaps, parse_digest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dataminr"
FIRST = FIXTURES / "01_2026-11-16_1400-1600HST_5_alerts.txt"
SECOND = FIXTURES / "02_2026-11-16_1800-2000HST_2_alerts.txt"
UTC = dt.UTC


def _inbox(raw_dir: Path, *files: Path) -> Path:
    inbox = raw_dir / "dataminr" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy(f, inbox / f.name)
    return inbox


def test_parse_digest_fields_and_variants() -> None:
    d = parse_digest(FIRST.read_text())
    assert d.watchlist == "Southern Border"
    # 14:00-16:00 HST is 00:00-02:00 UTC the next day (HST = UTC-10, no daylight time).
    assert (d.window_start, d.window_end) == (
        dt.datetime(2026, 11, 17, 0, tzinfo=UTC),
        dt.datetime(2026, 11, 17, 2, tzinfo=UTC),
    )
    assert d.total == len(d.alerts) == 5

    laser, blockade, protest, leak, pipeline = d.alerts
    assert laser.alert_id == "1000000001-1794880378000-3"
    assert laser.occurred_at == dt.datetime(2026, 11, 17, 1, 53, tzinfo=UTC)
    assert (laser.level, laser.is_update, laser.place) == (
        "Alert",
        False,
        "Nogales, Sonora, Mexico",
    )
    assert (laser.source_kind, laser.platform) == ("Reporter", "X")
    # First Alert's labels are swapped: the Spanish is the post as written.
    assert laser.post_language == "SPANISH"
    assert laser.post_original is not None
    assert laser.post_original.startswith("Un láser")
    assert laser.post_english is not None
    assert laser.post_english.startswith("A laser")
    assert laser.original_url == "https://x.com/example_reporter/status/1000000000000000001"

    assert (blockade.level, blockade.place) == ("Urgent", "Culiacán, Sinaloa, Mexico")  # pin line
    assert protest.x_protest
    assert not laser.x_protest
    assert not blockade.x_protest

    assert (leak.level, leak.is_update, leak.place) == ("Alert", True, "Mexico")
    assert leak.excerpt_from == "Public Telegram Board"
    assert leak.excerpt is not None
    assert "10,000 customer records" in leak.excerpt
    assert leak.original_url is None  # only Dataminr links; the image is not a link

    assert pipeline.platform == "Ejemplo Noticias"


def test_alert_text_leaves_out_dataminr_links_and_images() -> None:
    for alert in parse_digest(FIRST.read_text()).alerts:
        text = alert.text()
        assert "dataminr.com" not in text
        assert "key=" not in text
        assert "SYNTHETIC" not in text


def test_one_line_header_and_count_mismatch() -> None:
    assert len(parse_digest(SECOND.read_text()).alerts) == 2
    broken = FIRST.read_text().replace("5 total alerts", "6 total alerts")
    with pytest.raises(DataminrFormatError, match="says 6 alerts but 5"):
        parse_digest(broken)
    with pytest.raises(DataminrFormatError, match="window"):
        parse_digest("[First Alert]\n\nnothing here")


def test_find_gaps_between_windows_only() -> None:
    h = lambda n: dt.datetime(2026, 11, 17, n, tzinfo=UTC)  # noqa: E731
    assert find_gaps([(h(0), h(2)), (h(2), h(4)), (h(6), h(8)), (h(4), h(6))]) == []
    assert find_gaps([(h(0), h(2)), (h(4), h(6))]) == [(h(2), h(4))]
    assert find_gaps([]) == []


def test_inbox_ingest_stores_alerts_drops_x_protests_and_flags_the_gap(
    seeded: Session, raw_dir: Path
) -> None:
    inbox = _inbox(raw_dir, FIRST, SECOND)
    assert dataminr.run_inbox() == 0

    docs = {d.source_key: d for d in seeded.scalars(select(Document))}
    # 5 + 2 alerts, minus the X protest, minus the pipeline alert delivered twice.
    assert len(docs) == 5
    assert "alert:3000000003-1794878926000-3" not in docs
    laser = docs["alert:1000000001-1794880378000-3"]
    src = seeded.get_one(Source, laser.source_id)
    assert (src.slug, src.reliability, src.source_type) == ("dataminr", "D", "email")
    assert laser.language == "es"
    assert laser.pipeline_status == "new"
    assert laser.published_at == dt.datetime(2026, 11, 17, 1, 53, tzinfo=UTC)
    assert laser.source_url == "https://x.com/example_reporter/status/1000000000000000001"
    assert laser.original_text is not None
    assert "Original post (SPANISH" in laser.original_text
    pipeline = docs["alert:5000000005-1794867600000-3"]
    assert (
        pipeline.canonical_url
        == "https://noticias.example.com/local/toma-clandestina-salamanca.html"
    )
    assert docs["alert:4000000004-1794880276366-1"].language == "en"

    # Inbox emptied; both files archived under data/raw/dataminr/<date>/.
    assert not list(inbox.glob("*.txt"))
    archived = [p for p in (raw_dir / "dataminr").rglob("*.txt") if "inbox" not in p.parts]
    assert len(archived) == 2

    run = seeded.scalars(select(IngestRun).where(IngestRun.job == "dataminr")).one()
    assert (run.status, run.rows_inserted) == ("ok", 5)
    assert sum(f["dropped_x_protest"] for f in run.params["files"]) == 1
    gap = seeded.scalars(select(Alert).where(Alert.rule == "feed_gap")).one()
    assert gap.linked_records["gap_start"] == "2026-11-17T02:00:00+00:00"
    assert "16:00 to 18:00 HST" in gap.summary


def test_rerun_is_idempotent_and_gap_alert_is_not_repeated(seeded: Session, raw_dir: Path) -> None:
    _inbox(raw_dir, FIRST, SECOND)
    dataminr.run_inbox()
    _inbox(raw_dir, FIRST, SECOND)  # the connector re-delivers the same files
    dataminr.run_inbox()
    assert len(seeded.scalars(select(Document)).all()) == 5
    runs = seeded.scalars(select(IngestRun).order_by(IngestRun.id)).all()
    assert all(f.get("skipped") for f in runs[1].params["files"])
    assert len(seeded.scalars(select(Alert).where(Alert.rule == "feed_gap")).all()) == 1


def test_unparseable_file_is_set_aside_and_the_rest_still_load(
    seeded: Session, raw_dir: Path
) -> None:
    inbox = _inbox(raw_dir, FIRST)
    (inbox / "bad.txt").write_text("not a digest")
    with pytest.raises(DataminrFormatError, match=r"bad\.txt"):
        dataminr.run_inbox()
    assert (inbox / "failed" / "bad.txt").exists()
    assert len(seeded.scalars(select(Document)).all()) == 4
    run = seeded.scalars(select(IngestRun)).one()
    assert run.status == "error"


def test_explicit_file_is_left_in_place(seeded: Session, tmp_path: Path) -> None:
    path = shutil.copy(FIRST, tmp_path / FIRST.name)
    assert dataminr.run_inbox([Path(path)]) == 0
    assert Path(path).exists()
    assert len(seeded.scalars(select(Document)).all()) == 4


def test_stalled_digests_raise_one_alert(seeded: Session, raw_dir: Path) -> None:
    _inbox(raw_dir, SECOND)
    dataminr.run_inbox()  # may itself raise the alert, depending on today's clock
    late = dt.datetime(2026, 11, 17, 6, tzinfo=UTC) + dt.timedelta(hours=dataminr.STALL_HOURS)
    dataminr._check_stalled(now=late)
    dataminr._check_stalled(now=late + dt.timedelta(hours=1))
    stalled = seeded.scalars(select(Alert).where(Alert.rule == "feed_stalled")).all()
    assert len(stalled) == 1
    assert stalled[0].linked_records["newest_window_end"] == "2026-11-17T06:00:00+00:00"
    assert dataminr._check_stalled(now=dt.datetime(2026, 11, 17, 7, tzinfo=UTC)) is False
