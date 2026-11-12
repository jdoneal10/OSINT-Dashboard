"""CBP Public Data Portal ingester: Southwest border encounters and drug seizures by AOR.

Sources (document pages list every CSV with its posted date):
- Nationwide Encounters, by Area of Responsibility (``…-aor.csv``) → metric ``encounters``
- Nationwide Drug Seizures (``nationwide-drugs-…csv``) → metrics ``seizure_events``,
  ``seizure_lbs``

Rules:
- Figures are revised until fiscal-year close, so each file is a new ``snapshot_date``
  (its posted date) and history is never overwritten. The API serves the latest snapshot.
- robots.txt disallows ``/sites/default/files/assets/documents/`` (where FY20-FY23 live).
  Those files are never fetched; you download them by hand and import them with
  ``make ingest SOURCE=cbp FILE=…``. Discovery still reads their posted dates from the page.
- Only the Southwest border is kept; USBP sectors and OFO field offices both.

CLI::

    python -m app.ingest cbp                 # newest encounters + drugs files, if not yet ingested
    python -m app.ingest cbp --all           # every robots-allowed multi-year/full-year file
    python -m app.ingest cbp --file PATH     # import a manually downloaded file
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningInsert

from app.db.models import BorderMetric, Node
from app.db.session import session_factory
from app.ingest.http import PoliteClient
from app.ingest.raw import sha256_bytes, write_raw
from app.ingest.runs import RunContext, file_already_ingested, ingest_run, source_id

log = logging.getLogger(__name__)

SOURCE = "cbp"
JOB = "cbp"
BASE = "https://www.cbp.gov"
BLOCKED_PREFIX = "/sites/default/files/assets/documents/"

Kind = Literal["encounters", "drugs"]
DOC_PAGES: dict[Kind, str] = {
    "encounters": f"{BASE}/document/stats/nationwide-encounters",
    "drugs": f"{BASE}/document/stats/nationwide-drug-seizures",
}

ENCOUNTERS_HEADER = [
    "Fiscal Year",
    "Month Grouping",
    "Month (abbv)",
    "Component",
    "Land Border Region",
    "Area of Responsibility",
    "AOR (Abbv)",
    "Demographic",
    "Citizenship",
    "Title of Authority",
    "Encounter Type",
    "Encounter Count",
]
DRUGS_HEADER = [
    "FY",
    "Month (abbv)",
    "Component",
    "Region",
    "Land Filter",
    "Area of Responsibility",
    "Drug Type",
    "Count of Event",
    "Sum Qty (lbs)",
]
MONTH_NUM = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}

_ENCOUNTERS_FILE = re.compile(r"nationwide-encounters-.*-aor(_\d+)?\.csv$")
_DRUGS_FILE = re.compile(r"nationwide-drugs-.*\.csv$")
_SERIES = re.compile(r"(fy\d{2}-fy\d{2})")


class CbpFormatError(ValueError):
    """A CBP file does not have the expected header; upstream format changed."""


class BlockedPathError(ValueError):
    """Refusing to fetch a path that robots.txt disallows."""


# --------------------------------------------------------------------------- discovery


@dataclass(frozen=True)
class Listing:
    kind: Kind
    url: str
    title: str
    posted: dt.date

    @property
    def blocked(self) -> bool:
        return urlsplit(self.url).path.startswith(BLOCKED_PREFIX)

    @property
    def filename(self) -> str:
        return urlsplit(self.url).path.rsplit("/", 1)[-1]

    @property
    def series(self) -> str:
        m = _SERIES.search(self.filename)
        return m.group(1) if m else self.filename

    @property
    def fytd(self) -> bool:
        return "(FYTD)" in self.title


class _AttachmentTable(HTMLParser):
    """Collect (href, title, date) from the page's attachment table rows."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, str, str]] = []
        self._in_row = False
        self._href: str | None = None
        self._text: list[str] = []
        self._date: str | None = None
        self._in_a = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "tr":
            self._in_row, self._href, self._text, self._date = True, None, [], None
        elif tag == "a" and self._in_row and self._href is None:
            self._href = a.get("href")
            self._in_a = True
        elif tag == "td" and self._in_row:
            value = a.get("data-sort-value") or ""
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                self._date = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_a = False
        elif tag == "tr" and self._in_row:
            if self._href and self._date:
                self.rows.append((self._href, " ".join("".join(self._text).split()), self._date))
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._text.append(data)


def parse_listing(kind: Kind, html: str) -> list[Listing]:
    parser = _AttachmentTable()
    parser.feed(html)
    pattern = _ENCOUNTERS_FILE if kind == "encounters" else _DRUGS_FILE
    out = []
    for href, title, date in parser.rows:
        url = urljoin(BASE, href)
        if pattern.search(urlsplit(url).path):
            posted = dt.datetime.strptime(date, "%m/%d/%Y").date()  # noqa: DTZ007 — a date
            out.append(Listing(kind=kind, url=url, title=title, posted=posted))
    out.sort(key=lambda listing: listing.posted, reverse=True)
    return out


def discover(client: PoliteClient, kind: Kind) -> list[Listing]:
    resp = client.get(DOC_PAGES[kind])
    resp.raise_for_status()
    return parse_listing(kind, resp.text)


def select_files(listings: list[Listing], *, all_series: bool) -> list[Listing]:
    """Newest allowed file, or (``all_series``) the newest allowed file per fiscal-year series.

    Blocked files are never selected; they are imported manually.
    """
    allowed = [x for x in listings if not x.blocked]
    if not all_series:
        return allowed[:1]
    newest: dict[str, Listing] = {}
    for listing in allowed:  # already newest first
        newest.setdefault(listing.series, listing)
    return sorted(newest.values(), key=lambda x: x.posted)


# --------------------------------------------------------------------------- parsing


def fiscal_month(fy: int, month_abbv: str) -> dt.date:
    """CBP fiscal year N runs Oct (N-1) .. Sep N."""
    m = MONTH_NUM[month_abbv.strip().upper()[:3]]
    return dt.date(fy - 1 if m >= 10 else fy, m, 1)


def _num(text: str) -> Decimal:
    cleaned = text.replace(",", "").strip()
    return Decimal(cleaned) if cleaned else Decimal(0)


@dataclass(frozen=True)
class MetricRow:
    metric: str
    aor_label: str
    fiscal_year: int
    month: dt.date
    dimensions: tuple[tuple[str, str], ...]
    value: Decimal
    unit: str | None

    @property
    def dimension_key(self) -> str:
        return "|".join(f"{k}={v}" for k, v in self.dimensions)


def _reader(content: bytes, expected: list[str]) -> Iterator[dict[str, str]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if header != expected:
        raise CbpFormatError(f"unexpected header {header!r}; expected {expected!r}")
    for row in reader:
        yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def parse_encounters(content: bytes) -> Iterator[MetricRow]:
    for r in _reader(content, ENCOUNTERS_HEADER):
        if r["Land Border Region"] != "Southwest Land Border":
            continue
        fy = int(r["Fiscal Year"])
        yield MetricRow(
            metric="encounters",
            aor_label=r["Area of Responsibility"],
            fiscal_year=fy,
            month=fiscal_month(fy, r["Month (abbv)"]),
            dimensions=(
                ("citizenship", r["Citizenship"]),
                ("component", r["Component"]),
                ("demographic", r["Demographic"]),
                ("encounter_type", r["Encounter Type"]),
                ("title", r["Title of Authority"]),
            ),
            value=_num(r["Encounter Count"]),
            unit="persons",
        )


def parse_drugs(content: bytes) -> Iterator[MetricRow]:
    for r in _reader(content, DRUGS_HEADER):
        if r["Region"] != "Southwest Border":
            continue
        fy = int(r["FY"])
        dims = (
            ("component", r["Component"]),
            ("drug_type", r["Drug Type"]),
            ("land_filter", r["Land Filter"]),
        )
        label, month = r["Area of Responsibility"], fiscal_month(fy, r["Month (abbv)"])
        for metric, value, unit in (
            ("seizure_events", _num(r["Count of Event"]), "events"),
            ("seizure_lbs", _num(r["Sum Qty (lbs)"]), "lbs"),
        ):
            yield MetricRow(
                metric=metric,
                aor_label=label,
                fiscal_year=fy,
                month=month,
                dimensions=dims,
                value=value,
                unit=unit,
            )


def detect_kind(content: bytes) -> Kind:
    first = content.decode("utf-8-sig", errors="replace").splitlines()[0]
    header = [h.strip() for h in next(csv.reader([first]))]
    if header == ENCOUNTERS_HEADER:
        return "encounters"
    if header == DRUGS_HEADER:
        return "drugs"
    raise CbpFormatError(f"unrecognized CBP header: {header!r}")


def aggregate(rows: Iterable[MetricRow]) -> list[MetricRow]:
    """Sum duplicate keys so one upsert batch never touches the same row twice."""
    totals: dict[tuple[Any, ...], Decimal] = defaultdict(Decimal)
    first: dict[tuple[Any, ...], MetricRow] = {}
    for row in rows:
        key = (row.metric, row.aor_label.upper(), row.month, row.dimensions)
        totals[key] += row.value
        first.setdefault(key, row)
    return [
        MetricRow(
            metric=r.metric,
            aor_label=r.aor_label,
            fiscal_year=r.fiscal_year,
            month=r.month,
            dimensions=r.dimensions,
            value=totals[k],
            unit=r.unit,
        )
        for k, r in first.items()
    ]


# --------------------------------------------------------------------------- loading


def aor_index(session: Session) -> dict[str, int]:
    """Upper-cased AOR label → node id, for USBP sectors and OFO field offices."""
    rows = session.execute(
        select(Node.id, Node.name, Node.node_type).where(
            Node.node_type.in_(["usbp_sector", "ofo_field_office"])
        )
    ).all()
    return {name.upper(): node_id for node_id, name, _ in rows}


def load_rows(
    session: Session,
    rows: list[MetricRow],
    *,
    source_url: str,
    snapshot: dt.date,
    retrieved_at: dt.datetime,
) -> tuple[int, int, set[str]]:
    """Upsert rows for one snapshot. Returns (inserted, updated, unknown AOR labels)."""
    sid = source_id(session, SOURCE)
    index = aor_index(session)
    unknown: set[str] = set()
    inserted = updated = 0
    batch_size = 1000
    for start in range(0, len(rows), batch_size):
        values = []
        for r in rows[start : start + batch_size]:
            node_id = index.get(r.aor_label.upper())
            if node_id is None:
                unknown.add(r.aor_label)
            values.append(
                {
                    "source_id": sid,
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                    "snapshot_date": snapshot,
                    "metric": r.metric,
                    "aor_node_id": node_id,
                    "aor_label": r.aor_label,
                    "fiscal_year": r.fiscal_year,
                    "month": r.month,
                    "dimensions": dict(r.dimensions),
                    "dimension_key": r.dimension_key,
                    "value": r.value,
                    "unit": r.unit,
                }
            )
        base = insert(BorderMetric).values(values)
        upsert: ReturningInsert[Any] = base.on_conflict_do_update(
            constraint="uq_border_metrics_snapshot",
            set_={
                "value": base.excluded.value,
                "aor_node_id": base.excluded.aor_node_id,
                "retrieved_at": base.excluded.retrieved_at,
                "source_url": base.excluded.source_url,
            },
        ).returning(literal_column("(xmax = 0)"))
        for (was_insert,) in session.execute(upsert):
            if was_insert:
                inserted += 1
            else:
                updated += 1
    return inserted, updated, unknown


def ingest_content(
    run: RunContext,
    content: bytes,
    *,
    source_url: str,
    snapshot: dt.date,
    kind: Kind | None = None,
) -> None:
    kind = kind or detect_kind(content)
    parsed = parse_encounters(content) if kind == "encounters" else parse_drugs(content)
    rows = aggregate(parsed)
    retrieved_at = dt.datetime.now(dt.UTC)
    with session_factory()() as session, session.begin():
        ins, upd, unknown = load_rows(
            session, rows, source_url=source_url, snapshot=snapshot, retrieved_at=retrieved_at
        )
    run.inserted += ins
    run.updated += upd
    if unknown:
        log.warning("unmapped Southwest AOR labels (stored with no node): %s", sorted(unknown))
    log.info(
        "%s %s snapshot %s: %d rows (+%d ~%d)", kind, source_url, snapshot, len(rows), ins, upd
    )


def _record_file(run: RunContext, sha: str, url: str, snapshot: dt.date, kind: str) -> None:
    run.params.setdefault("files", []).append(
        {"sha256": sha, "url": url, "snapshot_date": snapshot.isoformat(), "kind": kind}
    )


def run_remote(*, all_series: bool = False, client: PoliteClient | None = None) -> int:
    owns = client is None
    client = client or PoliteClient()
    try:
        with ingest_run(
            JOB, source_slug=SOURCE, params={"mode": "all" if all_series else "latest"}
        ) as run:
            for kind in ("encounters", "drugs"):
                for listing in select_files(discover(client, kind), all_series=all_series):
                    if listing.blocked:  # defense in depth; select_files already excludes these
                        raise BlockedPathError(listing.url)
                    resp = client.get(listing.url)
                    resp.raise_for_status()
                    content = resp.content
                    sha = sha256_bytes(content)
                    if file_already_ingested(JOB, sha):
                        log.info("unchanged, skipping %s", listing.filename)
                        continue
                    snap = write_raw(SOURCE, run.id, listing.filename, content)
                    run.raw_paths.append(str(snap.path))
                    ingest_content(
                        run, content, source_url=listing.url, snapshot=listing.posted, kind=kind
                    )
                    _record_file(run, sha, listing.url, listing.posted, kind)
    finally:
        if owns:
            client.close()
    return 0


def run_local(
    path: Path,
    *,
    snapshot: dt.date | None = None,
    client: PoliteClient | None = None,
) -> int:
    """Import a manually downloaded file. Its snapshot date is looked up on CBP's page by
    filename (so an old file never outranks newer revisions); pass ``snapshot`` to override."""
    content = path.read_bytes()
    kind = detect_kind(content)
    url = f"file://{path.name}"
    if snapshot is None:
        owns = client is None
        client = client or PoliteClient()
        try:
            match = next((x for x in discover(client, kind) if x.filename == path.name), None)
        finally:
            if owns:
                client.close()
        if match is None:
            raise ValueError(
                f"{path.name} is not listed on {DOC_PAGES[kind]}; pass --snapshot-date YYYY-MM-DD"
            )
        snapshot, url = match.posted, match.url
    sha = sha256_bytes(content)
    with ingest_run(JOB, source_slug=SOURCE, params={"mode": "local", "file": path.name}) as run:
        if file_already_ingested(JOB, sha):
            log.info("unchanged, skipping %s", path.name)
            return 0
        snap = write_raw(SOURCE, run.id, path.name, content)
        run.raw_paths.append(str(snap.path))
        ingest_content(run, content, source_url=url, snapshot=snapshot, kind=kind)
        _record_file(run, sha, url, snapshot, kind)
    return 0
