"""ACLED weekly aggregates, imported from the owner's manual download (ADR 0011).

    make ingest SOURCE=acled-weekly FILE="<path>/Latin-America-the-Caribbean_aggregated_...xlsx"

ACLED publishes regional workbooks of weekly counts: one row per week x admin1 x event
sub-type, with events, fatalities and population exposure. ``WEEK`` is the Saturday that
starts ACLED's Saturday-to-Friday week; this matches the event data exactly (checked on
2026-11-16: week of 2025-11-01, Mexico, 359 events and 149 fatalities in both).

Rules:
- Only countries in the current AOI are kept (Mexico; Central America waits for Phase 5).
  Other rows are counted in the run's params, not stored.
- Admin1 names are matched to the codes ACLED events already use. An unmatched name fails
  the whole import, so nothing lands half-mapped.
- Each file is a snapshot (``snapshot_date``, default the import day). Re-importing the same
  file is a no-op; a newer file adds a new snapshot and never overwrites history.
- The original file is copied to ``data/raw/acled-weekly/<date>/`` (gitignored).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import Boolean, literal_column
from sqlalchemy.dialects.postgresql import insert

from app.db.models import AcledWeekly
from app.db.session import session_factory
from app.ingest.acled import Aoi, load_aoi
from app.ingest.raw import sha256_bytes, write_raw
from app.ingest.runs import file_already_ingested, ingest_run, source_id
from app.reference.normalize import normalize_alias

log = logging.getLogger(__name__)

SOURCE = "acled-weekly"
JOB = "acled-weekly"
COLUMNS = (
    "WEEK", "REGION", "COUNTRY", "ADMIN1", "EVENT_TYPE", "SUB_EVENT_TYPE", "EVENTS",
    "FATALITIES", "POPULATION_EXPOSURE", "DISORDER_TYPE",
)  # fmt: skip
# ACLED country name -> ISO3, for the countries the AOI covers.
AOI_COUNTRIES = {"Mexico": "MEX"}
_THROUGH = re.compile(r"up_to_week_of-(\d{4}-\d{2}-\d{2})")
UPSERT_CHUNK = 2000


class AcledWeeklyFormatError(ValueError):
    """The workbook does not look like an ACLED weekly aggregate file."""


def through_from_name(filename: str) -> dt.date | None:
    m = _THROUGH.search(filename)
    return dt.date.fromisoformat(m.group(1)) if m else None


def _as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def read_rows(path: Path) -> Iterator[dict[str, Any]]:
    """Yield one dict per data row, keyed by the ACLED column names."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        missing = [c for c in COLUMNS if c not in header]
        if missing:
            raise AcledWeeklyFormatError(f"missing columns {missing}; got {header}")
        for row in rows:
            rec = dict(zip(header, row, strict=False))
            if rec.get("WEEK") is None:
                continue
            yield rec
    finally:
        wb.close()


def match_admin1(aoi: Aoi, name: str) -> str | None:
    """Exact name match (accent/case-insensitive), allowing long official forms."""
    norm = normalize_alias(name)
    for ref, code in aoi.names.items():
        if norm == ref or norm.startswith(ref + " de ") or ref.startswith(norm + " de "):
            return code
    return None


def parse(path: Path, aoi: Aoi) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows for AOI countries, plus counts of rows skipped by country."""
    out: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    unmatched: set[str] = set()
    for rec in read_rows(path):
        country = str(rec["COUNTRY"])
        iso3 = AOI_COUNTRIES.get(country)
        if iso3 is None:
            skipped[country] = skipped.get(country, 0) + 1
            continue
        week = _as_date(rec["WEEK"])
        if week.weekday() != 5:
            raise AcledWeeklyFormatError(f"WEEK {week} is not a Saturday")
        admin1 = str(rec["ADMIN1"])
        code = match_admin1(aoi, admin1)
        if code is None:
            unmatched.add(admin1)
            continue
        exposure = rec.get("POPULATION_EXPOSURE")
        out.append(
            {
                "week": week,
                "country_iso3": iso3,
                "admin1_code": code,
                "admin1_name": admin1,
                "event_type": str(rec["EVENT_TYPE"]),
                "sub_event_type": str(rec["SUB_EVENT_TYPE"]),
                "disorder_type": rec.get("DISORDER_TYPE") or None,
                "events": int(rec["EVENTS"] or 0),
                "fatalities": int(rec["FATALITIES"] or 0),
                "population_exposure": int(exposure) if exposure not in (None, "") else None,
            }
        )
    if unmatched:
        raise AcledWeeklyFormatError(
            f"admin1 names not matched to a reference area: {sorted(unmatched)}"
        )
    return out, skipped


def run_file(path: Path, *, snapshot: dt.date | None = None) -> int:
    snapshot = snapshot or dt.datetime.now(dt.UTC).date()
    content = path.read_bytes()
    sha = sha256_bytes(content)
    params: dict[str, Any] = {
        "file": path.name,
        "snapshot": snapshot.isoformat(),
        "through": (t.isoformat() if (t := through_from_name(path.name)) else None),
    }
    with ingest_run(JOB, source_slug=SOURCE, params=params) as run:
        if file_already_ingested(JOB, sha):
            log.info("unchanged, skipping %s", path.name)
            return 0
        run.raw_paths.append(str(write_raw(SOURCE, run.id, path.name, content).path))
        with session_factory()() as session:
            aoi = load_aoi(session, phase=2)
        rows, skipped = parse(path, aoi)
        now = dt.datetime.now(dt.UTC)
        with session_factory()() as session, session.begin():
            sid = source_id(session, SOURCE)
            for start in range(0, len(rows), UPSERT_CHUNK):
                chunk = [
                    r | {"source_id": sid, "source_url": f"file://{path.name}",
                         "retrieved_at": now, "snapshot_date": snapshot}
                    for r in rows[start : start + UPSERT_CHUNK]
                ]  # fmt: skip
                base = insert(AcledWeekly).values(chunk)
                stmt = base.on_conflict_do_update(
                    constraint="uq_acled_weekly_snapshot",
                    set_={
                        "events": base.excluded.events,
                        "fatalities": base.excluded.fatalities,
                        "population_exposure": base.excluded.population_exposure,
                        "retrieved_at": base.excluded.retrieved_at,
                    },
                ).returning(literal_column("(xmax = 0)", Boolean))
                for (was_insert,) in session.execute(stmt):
                    run.inserted += int(was_insert)
                    run.updated += int(not was_insert)
        weeks = [r["week"] for r in rows]
        run.params |= {
            "files": [{"sha256": sha, "file": path.name}],
            "rows": len(rows),
            "first_week": min(weeks).isoformat() if weeks else None,
            "last_week": max(weeks).isoformat() if weeks else None,
            "skipped_outside_aoi": skipped,
        }
        log.info(
            "ACLED weekly %s: %d rows kept, skipped outside AOI: %s", path.name, len(rows), skipped
        )
    return 0
