"""SESNSP municipal crime incidence (fuero común), imported from manually downloaded files.

SESNSP serves its files from SharePoint, which refuses automated downloads (HTTP 403), so
the owner downloads them and this module imports local CSVs (ADR 0004):

    make ingest SOURCE=sesnsp FILE="data/raw/sesnsp/manual/RNID-Delitos_Municipal-2026-sep2026.csv"

Rules:
- Two methodologies are NOT comparable: rows dated <= 2025 are series ``2015-2025``,
  2026 onward is series ``2026``. They are stored and served separately.
- Only TCO-relevant crime types are kept (``KEEP``); everything else is skipped.
- Only non-zero values are stored. Within a series' covered months, a missing row means 0.
- Months after the file's data cutoff are placeholders (the 2026 file carries 0 for
  months that have not happened) and are never stored. The cutoff comes from the file
  name (e.g. ``sep2026`` / ``dic25``) or ``--through YYYY-MM``.
- Each file is a snapshot (``snapshot_date``); later revisions add rows, never overwrite.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, literal_column
from sqlalchemy.dialects.postgresql import insert

from app.db.models import CrimeIncidence
from app.db.session import session_factory
from app.ingest.raw import sha256_bytes
from app.ingest.runs import file_already_ingested, ingest_run, source_id
from app.reference.inegi import CVE_ENT_ISO

log = logging.getLogger(__name__)

SOURCE = "sesnsp"
JOB = "sesnsp"
HEADER = [
    "Año", "Clave_Ent", "Entidad", "Cve. Municipio", "Municipio", "Bien jurídico afectado",
    "Tipo de delito", "Subtipo de delito", "Modalidad", "Enero", "Febrero", "Marzo", "Abril",
    "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]  # fmt: skip
MONTH_COLUMNS = HEADER[9:]
# Crime types kept (tipo -> allowed subtypes, None = all). TCO-relevant violence and markets.
KEEP: dict[str, set[str] | None] = {
    "Homicidio": {"Homicidio doloso"},
    "Feminicidio": None,
    "Secuestro": None,
    "Extorsión": None,
    "Narcomenudeo": None,
    "Privación ilegal de la libertad": None,
}
_MONTHS_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip
_CUTOFF = re.compile(
    r"(?<![a-z])(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[_\s-]?(\d{4}|\d{2})"
)
UPSERT_CHUNK = 2000


class SesnspFormatError(ValueError):
    """The file does not have the expected SESNSP municipal header."""


def methodology_for(year: int) -> str:
    return "2015-2025" if year <= 2025 else "2026"


def data_cutoff(filename: str) -> dt.date | None:
    """First day of the last month with real data, from names like ``...-sep2026.csv``.

    For names with several dates (``dic25_corte_sep26``: data to Dec 2025, extracted Sep
    2026) the FIRST is the data cutoff; ``corte`` dates are extraction dates.
    """
    name = filename.lower()
    for m in _CUTOFF.finditer(name):
        if name[max(0, m.start() - 6) : m.start()].endswith("corte_"):
            continue
        year = int(m.group(2))
        year = year + 2000 if year < 100 else year
        return dt.date(year, _MONTHS_ES[m.group(1)], 1)
    return None


def snapshot_from_name(filename: str) -> dt.date | None:
    """Extraction date: the ``corte`` date if present, else the data cutoff month's end."""
    name = filename.lower()
    corte = re.search(r"corte_(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)(\d{2,4})", name)
    if corte:
        year = int(corte.group(2))
        year = year + 2000 if year < 100 else year
        month = _MONTHS_ES[corte.group(1)]
    else:
        cut = data_cutoff(filename)
        if cut is None:
            return None
        year, month = cut.year, cut.month
    next_month = dt.date(year + month // 12, month % 12 + 1, 1)
    return next_month - dt.timedelta(days=1)


def _open_text(path: Path) -> io.TextIOWrapper:
    """SESNSP ships UTF-8 (2026) and Latin-1 (2015-2025) files."""
    with path.open("rb") as fh:
        head = fh.read(1 << 20)
    try:
        head.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "latin-1"
    return io.TextIOWrapper(path.open("rb"), encoding=encoding, newline="")


def parse(path: Path, through: dt.date) -> Iterator[dict[str, Any]]:
    """Yield one dict per (municipality, month, crime) with a non-zero count."""
    with _open_text(path) as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        if header != HEADER:
            raise SesnspFormatError(f"unexpected header {header!r}")
        for row in reader:
            rec = dict(zip(HEADER, row, strict=False))
            crime = rec["Tipo de delito"].strip()
            allowed = KEEP.get(crime, ...)
            if allowed is ...:
                continue
            subtype = rec["Subtipo de delito"].strip()
            if allowed is not None and subtype not in allowed:
                continue
            year = int(rec["Año"])
            ent = rec["Clave_Ent"].strip().zfill(2)
            admin2 = rec["Cve. Municipio"].strip().zfill(5)
            modality = rec["Modalidad"].strip()
            for i, col in enumerate(MONTH_COLUMNS, start=1):
                month = dt.date(year, i, 1)
                if month > through:
                    break  # placeholder months after the data cutoff
                value_text = (rec.get(col) or "").strip()
                value = int(value_text) if value_text.isdigit() else 0
                if value == 0:
                    continue
                yield {
                    "methodology": methodology_for(year),
                    "month": month,
                    "admin1_code": CVE_ENT_ISO.get(ent, f"MX-{ent}"),
                    "admin2_code": admin2,
                    "crime_type": crime,
                    "crime_subtype": subtype or None,
                    "modality": modality or None,
                    "crime_key": "|".join([crime, subtype, modality]),
                    "value": value,
                }


def run_file(path: Path, *, through: dt.date | None = None, snapshot: dt.date | None = None) -> int:
    through = through or data_cutoff(path.name)
    snapshot = snapshot or snapshot_from_name(path.name)
    if through is None or snapshot is None:
        raise ValueError(
            f"cannot read the data cutoff from {path.name!r}; pass --through YYYY-MM "
            "and --snapshot-date YYYY-MM-DD"
        )
    sha = sha256_bytes(path.read_bytes())
    params = {"file": path.name, "through": through.isoformat(), "snapshot": snapshot.isoformat()}
    with ingest_run(JOB, source_slug=SOURCE, params=params) as run:
        if file_already_ingested(JOB, sha):
            log.info("unchanged, skipping %s", path.name)
            return 0
        totals: dict[tuple[Any, ...], dict[str, Any]] = {}
        sums: dict[tuple[Any, ...], int] = defaultdict(int)
        for rec in parse(path, through):
            key = (rec["methodology"], rec["admin2_code"], rec["month"], rec["crime_key"])
            sums[key] += rec["value"]
            totals.setdefault(key, rec)
        rows = [totals[k] | {"value": v} for k, v in sums.items()]
        now = dt.datetime.now(dt.UTC)
        with session_factory()() as session, session.begin():
            sid = source_id(session, SOURCE)
            for start in range(0, len(rows), UPSERT_CHUNK):
                chunk = [
                    r | {"source_id": sid, "source_url": f"file://{path.name}",
                         "retrieved_at": now, "snapshot_date": snapshot}
                    for r in rows[start : start + UPSERT_CHUNK]
                ]  # fmt: skip
                base = insert(CrimeIncidence).values(chunk)
                stmt = base.on_conflict_do_update(
                    constraint="uq_crime_incidence_snapshot",
                    set_={"value": base.excluded.value, "retrieved_at": base.excluded.retrieved_at},
                ).returning(literal_column("(xmax = 0)", Boolean))
                for (was_insert,) in session.execute(stmt):
                    run.inserted += int(was_insert)
                    run.updated += int(not was_insert)
        run.params |= {
            "files": [{"sha256": sha, "file": path.name}],
            "rows": len(rows),
            "series": sorted({r["methodology"] for r in rows}),
        }
        log.info("SESNSP %s: %d non-zero municipal-month values", path.name, len(rows))
    return 0
