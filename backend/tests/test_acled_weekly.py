"""ACLED weekly aggregates: import, admin1 matching and the combined series (ADR 0011).

Workbooks are synthetic, built in the test with the column layout of ACLED's published file.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.acled_series import series_meta, week_start, weekly_series
from app.db.models import AcledWeekly, Event, IngestRun, Source
from app.ingest import acled_weekly
from app.ingest.acled_weekly import AcledWeeklyFormatError

HEADER = [
    "WEEK", "REGION", "COUNTRY", "ADMIN1", "EVENT_TYPE", "SUB_EVENT_TYPE", "EVENTS",
    "FATALITIES", "POPULATION_EXPOSURE", "DISORDER_TYPE", "ID", "CENTROID_LATITUDE",
    "CENTROID_LONGITUDE",
]  # fmt: skip
NOW = dt.datetime(2026, 11, 16, tzinfo=dt.UTC)
SAT = dt.date(2025, 11, 1)  # a Saturday: ACLED weeks run Saturday to Friday


def _row(week: dt.date, admin1: str, events: int, fatalities: int = 0, *,
         country: str = "Mexico", event_type: str = "Battles",
         sub: str = "Armed clash") -> list[Any]:  # fmt: skip
    return [dt.datetime.combine(week, dt.time()), "Central America", country, admin1, event_type,
            sub, events, fatalities, None, "Political violence", 1, 24.8, -107.4]  # fmt: skip


def _workbook(path: Path, rows: list[list[Any]], header: list[str] = HEADER) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "ACLED Data"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def _file(tmp_path: Path, rows: list[list[Any]], name: str | None = None) -> Path:
    name = name or "Latin-America-the-Caribbean_aggregated_data_up_to_week_of-2025-11-29.xlsx"
    return _workbook(tmp_path / name, rows)


def _acled_event(session: Session, day: dt.date, admin1: str, fatalities: int = 1,
                 event_type: str = "Battles") -> None:  # fmt: skip
    sid = session.scalars(select(Source.id).where(Source.slug == "acled")).one()
    n = session.scalar(select(func.count()).select_from(Event)) or 0
    session.add(Event(source_id=sid, source_key=f"MEX{n}", retrieved_at=NOW, event_date=day,
                      event_type=event_type, fatalities=fatalities,
                      admin1_code=admin1))  # fmt: skip
    session.flush()


def test_week_start_is_the_saturday() -> None:
    assert week_start(dt.date(2025, 11, 1)) == SAT  # Saturday itself
    assert week_start(dt.date(2025, 11, 7)) == SAT  # Friday ends the week
    assert week_start(dt.date(2025, 11, 8)) == dt.date(2025, 11, 8)


def test_import_keeps_aoi_countries_matches_states_and_is_idempotent(
    seeded: Session, tmp_path: Path, raw_dir: Path
) -> None:
    path = _file(tmp_path, [
        _row(SAT, "Sinaloa", 5, 2),
        _row(SAT, "Coahuila", 1),  # short form of "Coahuila de Zaragoza"
        _row(SAT, "Michoacan de Ocampo", 3, 1),
        _row(SAT, "Escuintla", 9, country="Guatemala"),  # Central America waits for Phase 5
    ])  # fmt: skip
    snap = dt.date(2026, 11, 16)
    assert acled_weekly.run_file(path, snapshot=snap) == 0
    rows = seeded.execute(
        select(AcledWeekly.admin1_code, AcledWeekly.events, AcledWeekly.fatalities).order_by(
            AcledWeekly.admin1_code
        )
    ).all()
    assert [tuple(r) for r in rows] == [("MX-COA", 1, 0), ("MX-MIC", 3, 1), ("MX-SIN", 5, 2)]
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == "acled-weekly")).one()
    assert run.params["skipped_outside_aoi"] == {"Guatemala": 1}
    assert run.params["through"] == "2025-11-29"
    assert list(raw_dir.glob("acled-weekly/*/*.xlsx"))  # original kept under data/raw

    acled_weekly.run_file(path, snapshot=snap)  # same file again: no-op
    seeded.expire_all()
    assert seeded.scalar(select(func.count()).select_from(AcledWeekly)) == 3


def test_new_file_adds_a_snapshot_without_overwriting(seeded: Session, tmp_path: Path) -> None:
    acled_weekly.run_file(_file(tmp_path, [_row(SAT, "Sinaloa", 5)]), snapshot=dt.date(2026, 11, 1))
    revised = _workbook(tmp_path / "revised_up_to_week_of-2025-11-29.xlsx",
                        [_row(SAT, "Sinaloa", 7)])  # fmt: skip
    acled_weekly.run_file(revised, snapshot=dt.date(2026, 11, 16))
    values = seeded.execute(
        select(AcledWeekly.snapshot_date, AcledWeekly.events).order_by(AcledWeekly.snapshot_date)
    ).all()
    assert [tuple(v) for v in values] == [(dt.date(2026, 11, 1), 5), (dt.date(2026, 11, 16), 7)]


def test_unmatched_state_fails_the_whole_import(seeded: Session, tmp_path: Path) -> None:
    path = _file(tmp_path, [_row(SAT, "Sinaloa", 5), _row(SAT, "Atlantis", 1)])
    with pytest.raises(AcledWeeklyFormatError, match="Atlantis"):
        acled_weekly.run_file(path)
    assert seeded.scalar(select(func.count()).select_from(AcledWeekly)) == 0
    run = seeded.scalars(select(IngestRun).where(IngestRun.job == "acled-weekly")).one()
    assert run.status == "error"


def test_non_saturday_week_and_missing_columns_are_rejected(
    seeded: Session, tmp_path: Path
) -> None:
    with pytest.raises(AcledWeeklyFormatError, match="not a Saturday"):
        acled_weekly.run_file(_file(tmp_path, [_row(dt.date(2025, 11, 3), "Sinaloa", 1)]))
    bad = _workbook(tmp_path / "bad.xlsx", [], header=["WEEK", "COUNTRY"])
    with pytest.raises(AcledWeeklyFormatError, match="missing columns"):
        acled_weekly.run_file(bad)


@pytest.fixture
def joined(seeded: Session, tmp_path: Path) -> Session:
    """Events through Saturday 2025-11-15; aggregates for 2025-11-01 to 2025-11-22."""
    for day in (dt.date(2025, 10, 27), dt.date(2025, 11, 3), dt.date(2025, 11, 4)):
        _acled_event(seeded, day, "MX-SIN")
    _acled_event(seeded, dt.date(2025, 11, 10), "MX-SIN")  # partial, newest released weeks
    _acled_event(seeded, dt.date(2025, 11, 15), "MX-SIN")
    seeded.commit()
    acled_weekly.run_file(_file(tmp_path, [
        _row(SAT, "Sinaloa", 99, 9),  # overlaps a full event week: must not be used
        _row(dt.date(2025, 11, 8), "Sinaloa", 6, 2),
        _row(dt.date(2025, 11, 15), "Sinaloa", 4, 1),
        _row(dt.date(2025, 11, 22), "Sinaloa", 3, 0),
        _row(dt.date(2025, 11, 22), "Sonora", 2, 1),
    ]), snapshot=dt.date(2026, 11, 16))  # fmt: skip
    return seeded


def test_each_week_comes_from_exactly_one_source(joined: Session) -> None:
    meta = series_meta(joined)
    assert meta.events_through == dt.date(2025, 11, 15)
    assert meta.horizon_week_end == dt.date(2025, 11, 7)  # last full week before the newest
    by_week: dict[dt.date, set[str]] = {}
    totals: dict[dt.date, int] = {}
    for r in weekly_series(joined, admin1=["MX-SIN"]):
        by_week.setdefault(r.week, set()).add(r.origin)
        totals[r.week] = totals.get(r.week, 0) + r.events
    assert by_week == {
        dt.date(2025, 10, 25): {"events"},
        SAT: {"events"},
        dt.date(2025, 11, 8): {"aggregate"},
        dt.date(2025, 11, 15): {"aggregate"},
        dt.date(2025, 11, 22): {"aggregate"},
    }
    assert totals[SAT] == 2  # the two event records, not the aggregate's 99
    assert totals[dt.date(2025, 11, 8)] == 6  # aggregate, not the one partial event


def test_without_aggregates_events_cover_every_week(seeded: Session) -> None:
    _acled_event(seeded, dt.date(2025, 11, 3), "MX-SIN")
    _acled_event(seeded, dt.date(2025, 11, 15), "MX-SIN")
    seeded.commit()
    weeks = {r.week for r in weekly_series(seeded)}
    assert weeks == {SAT, dt.date(2025, 11, 15)}


def test_api_series_and_state_totals(joined: Session, client: TestClient) -> None:
    body = client.get("/acled/weekly", params={"admin1": "MX-SIN"}).json()
    assert [(p["week"], p["events"], p["origin"]) for p in body["points"]] == [
        ("2025-10-25", 1, "events"),
        ("2025-11-01", 2, "events"),
        ("2025-11-08", 6, "aggregate"),
        ("2025-11-15", 4, "aggregate"),
        ("2025-11-22", 3, "aggregate"),
    ]
    assert body["meta"]["aggregate_last_week"] == "2025-11-22"

    states = client.get(
        "/acled/weekly/states", params={"start": "2025-11-08", "end": "2025-11-28"}
    ).json()
    assert states["origins"] == ["aggregate"]
    assert {i["admin1_code"]: i["events"] for i in states["items"]} == {"MX-SIN": 13, "MX-SON": 2}


def test_each_week_reads_the_newest_file_that_covers_it(joined: Session, tmp_path: Path) -> None:
    # A two-week update file extends the series; older weeks keep their older file.
    acled_weekly.run_file(_file(tmp_path, [
        _row(dt.date(2025, 11, 22), "Sinaloa", 5, 0),  # revised; Sonora not in this file
        _row(dt.date(2025, 11, 29), "Sinaloa", 7, 1),
    ], name="update.xlsx"), snapshot=dt.date(2026, 11, 25))  # fmt: skip
    meta = series_meta(joined)
    assert (meta.aggregate_snapshot, meta.aggregate_first_week, meta.aggregate_last_week) == (
        dt.date(2026, 11, 25), SAT, dt.date(2025, 11, 29))  # fmt: skip
    got = {(r.week, r.admin1_code): r.events for r in weekly_series(joined)
           if r.origin == "aggregate"}  # fmt: skip
    assert got == {
        (dt.date(2025, 11, 8), "MX-SIN"): 6,  # only in the first file
        (dt.date(2025, 11, 15), "MX-SIN"): 4,
        (dt.date(2025, 11, 22), "MX-SIN"): 5,  # the week comes whole from the newer file
        (dt.date(2025, 11, 29), "MX-SIN"): 7,
    }
