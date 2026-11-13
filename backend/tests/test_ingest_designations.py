from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Actor, Designation, designation_actors
from app.ingest import designations
from app.ingest.http import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "designations"


class Gov:
    def __init__(self) -> None:
        self.sdn = (FIX / "sdn.xml").read_bytes()
        self.etag = '"v1"'
        self.calls: list[httpx.Request] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.endswith("SDN.XML"):
            if req.headers.get("if-none-match") == self.etag:
                return httpx.Response(304)
            return httpx.Response(200, content=self.sdn, headers={"ETag": self.etag})
        if req.url.path == "/api/v1/documents.json":
            return httpx.Response(200, content=(FIX / "fr.json").read_bytes())
        return httpx.Response(404)

    def client(self) -> PoliteClient:
        return PoliteClient(
            transport=httpx.MockTransport(self.handler), min_interval=0, sleep=lambda _s: None
        )


def _run(gov: Gov) -> None:
    with gov.client() as client:
        designations.run_designations(client)


def _by_key(session: Session) -> dict[str, Designation]:
    session.expire_all()
    return {d.source_key: d for d in session.scalars(select(Designation))}


def _linked(session: Session, designation: Designation) -> set[str]:
    return set(
        session.scalars(
            select(Actor.slug)
            .join(designation_actors, designation_actors.c.actor_id == Actor.id)
            .where(designation_actors.c.designation_id == designation.id)
        )
    )


@pytest.mark.parametrize(
    ("title", "names"),
    [
        (
            "Foreign Terrorist Organization Designations of Tren de Aragua, Cartel de Sinaloa, "
            "and La Nueva Familia Michoacana",
            ["Tren de Aragua", "Cartel de Sinaloa", "La Nueva Familia Michoacana"],
        ),
        (
            "Foreign Terrorist Organization Designation of Juarez Cartel and Los Viagras",
            ["Juarez Cartel", "Los Viagras"],
        ),
        (
            "Designation of Example Group as a Specially Designated Global Terrorist",
            ["Example Group"],
        ),
        ("Notice of Public Meeting", []),
    ],
)
def test_names_from_title(title: str, names: list[str]) -> None:
    assert designations.names_from_title(title) == names


def test_sdn_filtering_and_individual_privacy(seeded: Session) -> None:
    _run(Gov())
    rows = _by_key(seeded)
    sdn = {k: v for k, v in rows.items() if k.startswith("sdn:")}
    assert set(sdn) == {"sdn:900001", "sdn:900002"}  # CUBA program / Colombia-only excluded

    cjng = sdn["sdn:900001"]
    assert (cjng.designation_type, cjng.action, cjng.action_date) == (
        "sdn",
        "listed",
        dt.date(2026, 11, 9),
    )
    assert "cjng" in _linked(seeded, cjng)

    person = sdn["sdn:900002"]
    assert person.listed_parties == [{"name": "SINTETICO, Persona", "type": "individual"}]
    assert person.title == "SDN listing"
    assert _linked(seeded, person) == set()  # individuals never become/link to actors
    stored = json.dumps([person.listed_parties, person.title, person.program])
    for secret in ("X9999999", "1980", "Culiacan", "Passport"):
        assert secret not in stored


def test_unchanged_list_is_skipped_by_etag(seeded: Session) -> None:
    gov = Gov()
    _run(gov)
    _run(gov)
    sdn_calls = [c for c in gov.calls if c.url.path.endswith("SDN.XML")]
    assert sdn_calls[-1].headers.get("if-none-match") == '"v1"'
    assert len(_by_key(seeded)) == 4  # 2 SDN + 2 FR designation notices


def test_removed_listing_recorded_once(seeded: Session) -> None:
    gov = Gov()
    _run(gov)
    gov.sdn = gov.sdn.replace(b"<uid>900001</uid>", b"<uid>900099</uid>").replace(
        b"11/09/2026", b"11/16/2026"
    )
    gov.etag = '"v2"'
    _run(gov)
    _run(gov)  # unchanged v2: no duplicate removal
    rows = _by_key(seeded)
    removed = [r for r in rows.values() if r.action == "removed"]
    assert [r.source_key for r in removed] == ["sdn:900001:removed:2026-11-16"]
    assert rows["sdn:900001"].action_date == dt.date(2026, 11, 9)  # first-seen date kept


def test_federal_register_notices_link_actors(seeded: Session) -> None:
    _run(Gov())
    rows = _by_key(seeded)
    fto = rows["2099-00001"]
    assert (fto.designation_type, fto.program, fto.action) == ("fto", "INA 219", "designated")
    assert [p["name"] for p in fto.listed_parties] == [
        "Cartel del Golfo",
        "Synthetic Cartel",
        "La Nueva Familia Michoacana",
    ]
    assert _linked(seeded, fto) == {"cartel-del-golfo", "la-nueva-familia-michoacana"}
    sdgt = rows["2099-00002"]
    assert (sdgt.designation_type, sdgt.program) == ("sdgt", "EO 13224")
    assert "2099-00003" not in rows  # not a designation notice
    assert "2099-00004" not in rows  # designation outside the AOI (no regional link)
