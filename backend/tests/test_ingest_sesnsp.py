from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CrimeIncidence
from app.ingest import sesnsp

FIX = Path(__file__).parent / "fixtures" / "sesnsp"
OLD = FIX / "municipal-delitos-2015-2025-dic25_corte_sep26.csv"
NEW = FIX / "RNID-Delitos_Municipal-2026-sep2026.csv"


@pytest.mark.parametrize(
    ("name", "cutoff", "snapshot"),
    [
        ("RNID-Delitos_Municipal-2026-sep2026.csv", dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
        (
            "Municipal-Delitos - (2015-2025) dic25_corte_sep26.csv",
            dt.date(2025, 12, 1),
            dt.date(2026, 9, 30),
        ),
        ("whatever.csv", None, None),
    ],
)
def test_cutoff_and_snapshot_from_name(
    name: str, cutoff: dt.date | None, snapshot: dt.date | None
) -> None:
    assert sesnsp.data_cutoff(name) == cutoff
    assert sesnsp.snapshot_from_name(name) == snapshot


def _rows(session: Session) -> list[CrimeIncidence]:
    session.expire_all()
    return list(session.scalars(select(CrimeIncidence).order_by(CrimeIncidence.month)))


def test_latin1_file_filters_types_and_sums_duplicates(seeded: Session) -> None:
    sesnsp.run_file(OLD)
    rows = _rows(seeded)
    kinds = {(r.crime_type, r.crime_subtype) for r in rows}
    assert kinds == {("Homicidio", "Homicidio doloso"), ("Secuestro", "Secuestro extorsivo")}
    homicide = [r for r in rows if r.crime_type == "Homicidio"]
    assert [(r.month, r.value) for r in homicide] == [
        (dt.date(2024, 1, 1), 10),
        (dt.date(2024, 3, 1), 5),
        (dt.date(2024, 12, 1), 3),
    ]  # zeros not stored
    kidnap = next(r for r in rows if r.crime_type == "Secuestro")
    assert (kidnap.value, kidnap.admin2_code, kidnap.admin1_code) == (3, "01001", "MX-AGU")
    assert {r.methodology for r in rows} == {"2015-2025"}
    assert {r.snapshot_date for r in rows} == {dt.date(2026, 9, 30)}


def test_2026_series_separate_and_cutoff_respected(seeded: Session) -> None:
    sesnsp.run_file(NEW)
    rows = _rows(seeded)
    assert {r.methodology for r in rows} == {"2026"}
    assert [(r.crime_type, r.month, r.value) for r in rows] == [
        ("Homicidio", dt.date(2026, 1, 1), 7),
        ("Extorsión", dt.date(2026, 3, 1), 1),
        ("Homicidio", dt.date(2026, 9, 1), 2),
    ]  # October's 99 is after the September cutoff -> never stored
    assert rows[0].admin2_code == "02004"


def test_reimport_is_idempotent(seeded: Session) -> None:
    sesnsp.run_file(NEW)
    before = len(_rows(seeded))
    sesnsp.run_file(NEW)  # same bytes -> skipped
    assert len(_rows(seeded)) == before


def test_header_change_fails_loudly(seeded: Session, tmp_path: Path) -> None:
    bad = tmp_path / "x-sep2026.csv"
    bad.write_text("Year,Entity\n2026,1\n", encoding="utf-8")
    with pytest.raises(sesnsp.SesnspFormatError):
        sesnsp.run_file(bad)
