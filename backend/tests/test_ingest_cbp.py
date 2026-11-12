from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import BorderMetric, IngestRun, Node
from app.ingest import cbp
from app.ingest.http import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "cbp"
ROBOTS = "User-agent: *\nDisallow: /search/\nDisallow:  /sites/default/files/assets/documents/\n"


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(BorderMetric)) or 0


# --------------------------------------------------------------------------- pure parsing


@pytest.mark.parametrize(
    ("fy", "month", "expected"),
    [
        (2024, "OCT", dt.date(2023, 10, 1)),
        (2024, "DEC", dt.date(2023, 12, 1)),
        (2024, "JAN", dt.date(2024, 1, 1)),
        (2024, "SEP", dt.date(2024, 9, 1)),
    ],
)
def test_fiscal_month(fy: int, month: str, expected: dt.date) -> None:
    assert cbp.fiscal_month(fy, month) == expected


def test_parse_listing_and_selection() -> None:
    listings = cbp.parse_listing("encounters", (FIX / "nationwide-encounters.html").read_text())
    names = [x.filename for x in listings]
    assert "nationwide-encounters-fy23-fy26-sep-state.csv" not in names  # state files ignored
    assert names[0] == "nationwide-encounters-fy23-fy26-sep-aor.csv"  # newest first
    blocked = [x for x in listings if x.blocked]
    assert [x.filename for x in blocked] == ["nationwide-encounters-fy20-fy23-aor.csv"]
    assert blocked[0].posted == dt.date(2023, 11, 7)

    assert [x.filename for x in cbp.select_files(listings, all_series=False)] == [
        "nationwide-encounters-fy23-fy26-sep-aor.csv"
    ]
    assert [x.filename for x in cbp.select_files(listings, all_series=True)] == [
        "nationwide-encounters-fy21-fy24-aor.csv",
        "nationwide-encounters-fy22-fy25-aor.csv",
        "nationwide-encounters-fy23-fy26-sep-aor.csv",
    ]


def test_parse_encounters_filters_and_aggregates() -> None:
    rows = cbp.aggregate(cbp.parse_encounters((FIX / "encounters-aor.csv").read_bytes()))
    labels = {r.aor_label for r in rows}
    assert "Boston Field Office" not in labels  # Northern border filtered out
    sd = [r for r in rows if r.aor_label == "San Diego Sector"]
    assert len(sd) == 1  # duplicate rows summed
    assert sd[0].value == Decimal(1230)  # "1,200" + 30
    assert sd[0].month == dt.date(2023, 10, 1)
    assert "demographic=Single Adults" in sd[0].dimension_key


def test_parse_drugs_two_metrics_per_row() -> None:
    rows = list(cbp.parse_drugs((FIX / "nationwide-drugs.csv").read_bytes()))
    assert {r.aor_label for r in rows} == {
        "BIG BEND SECTOR",
        "EL PASO FIELD OFFICE",
        "TUCSON SECTOR",
    }
    tucson = {r.metric: r.value for r in rows if r.aor_label == "TUCSON SECTOR"}
    assert tucson == {"seizure_events": Decimal(9), "seizure_lbs": Decimal("1034.25")}


def test_header_change_fails_loudly() -> None:
    bad = b"FY,Month,Component\n2025,NOV,USBP\n"
    with pytest.raises(cbp.CbpFormatError):
        cbp.detect_kind(bad)
    with pytest.raises(cbp.CbpFormatError):
        list(cbp.parse_drugs(bad))


# --------------------------------------------------------------------------- database


def test_local_import_is_idempotent_and_maps_aors(seeded: Session) -> None:
    path = FIX / "encounters-aor.csv"
    snap = dt.date(2026, 10, 15)
    cbp.run_local(path, snapshot=snap)
    first = _count(seeded)
    assert first == 4  # SD (aggregated), RGV, Laredo FO, unknown

    cbp.run_local(path, snapshot=snap)  # same bytes → skipped by hash
    assert _count(seeded) == first

    rows = seeded.execute(
        select(BorderMetric.aor_label, Node.slug).outerjoin(
            Node, Node.id == BorderMetric.aor_node_id
        )
    ).all()
    mapping = dict(rows)
    assert mapping["San Diego Sector"] == "usbp-san-diego"
    assert mapping["Laredo Field Office"] == "ofo-laredo"
    assert mapping["Test Unknown Sector"] is None  # kept, not dropped


def test_revised_file_adds_snapshot_without_overwriting(seeded: Session, tmp_path: Path) -> None:
    original = (FIX / "nationwide-drugs.csv").read_bytes()
    cbp.run_local(FIX / "nationwide-drugs.csv", snapshot=dt.date(2026, 9, 4))
    revised = tmp_path / "nationwide-drugs.csv"
    revised.write_bytes(original.replace(b"14,120.5", b"15,130.5"))
    cbp.run_local(revised, snapshot=dt.date(2026, 10, 15))

    values = seeded.execute(
        select(BorderMetric.snapshot_date, BorderMetric.value)
        .where(
            BorderMetric.aor_label == "EL PASO FIELD OFFICE",
            BorderMetric.metric == "seizure_lbs",
        )
        .order_by(BorderMetric.snapshot_date)
    ).all()
    assert values == [
        (dt.date(2026, 9, 4), Decimal("120.500")),
        (dt.date(2026, 10, 15), Decimal("130.500")),
    ]


def _site(requests: list[str]) -> httpx.MockTransport:
    pages = {
        "/robots.txt": ROBOTS.encode(),
        "/document/stats/nationwide-encounters": (FIX / "nationwide-encounters.html").read_bytes(),
        "/document/stats/nationwide-drug-seizures": (
            FIX / "nationwide-drug-seizures.html"
        ).read_bytes(),
        "/sites/default/files/2026-10/nationwide-encounters-fy23-fy26-sep-aor.csv": (
            FIX / "encounters-aor.csv"
        ).read_bytes(),
        "/sites/default/files/2026-10/nationwide-drugs-fy23-fy26-sep.csv": (
            FIX / "nationwide-drugs.csv"
        ).read_bytes(),
    }

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req.url.path)
        body = pages.get(req.url.path)
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    return httpx.MockTransport(handler)


def _client(requests: list[str]) -> PoliteClient:
    return PoliteClient(transport=_site(requests), min_interval=0, sleep=lambda _s: None)


def test_remote_run_fetches_newest_and_never_blocked_paths(seeded: Session) -> None:
    requests: list[str] = []
    with _client(requests) as client:
        cbp.run_remote(client=client)
    assert not any(p.startswith(cbp.BLOCKED_PREFIX) for p in requests)
    assert _count(seeded) == 4 + 6  # encounters rows + 3 SW drug rows x 2 metrics
    snapshots = set(seeded.scalars(select(BorderMetric.snapshot_date).distinct()))
    assert snapshots == {dt.date(2026, 10, 15)}

    with _client(requests) as client:
        cbp.run_remote(client=client)  # unchanged files → no new rows
    assert _count(seeded) == 10
    runs = seeded.scalars(select(IngestRun.status).where(IngestRun.job == "cbp")).all()
    assert runs == ["ok", "ok"]


def test_local_import_looks_up_posted_date_for_blocked_file(
    seeded: Session, tmp_path: Path
) -> None:
    """Manual FY20 import: date comes from the page listing, file is never fetched."""
    manual = tmp_path / "nationwide-drugs-fy20-fy23.csv"
    manual.write_bytes((FIX / "nationwide-drugs.csv").read_bytes())
    requests: list[str] = []
    with _client(requests) as client:
        cbp.run_local(manual, client=client)
    assert "/sites/default/files/assets/documents/2023-Oct/nationwide-drugs-fy20-fy23.csv" not in (
        requests
    )
    assert set(seeded.scalars(select(BorderMetric.snapshot_date).distinct())) == {
        dt.date(2023, 10, 18)
    }


def test_local_import_of_unlisted_file_requires_snapshot_date(
    seeded: Session, tmp_path: Path
) -> None:
    unlisted = tmp_path / "mystery.csv"
    unlisted.write_bytes((FIX / "nationwide-drugs.csv").read_bytes())
    with _client([]) as client, pytest.raises(ValueError, match="snapshot-date"):
        cbp.run_local(unlisted, client=client)
