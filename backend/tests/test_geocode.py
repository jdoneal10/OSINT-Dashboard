from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.enrich.geocode import geocode, resolve_state
from app.reference.inegi_load import load

FIX = Path(__file__).parent / "fixtures" / "inegi"


@pytest.fixture
def gazetteer(seeded: Session, raw_dir: Path) -> Session:
    shutil.copytree(FIX, raw_dir / "reference" / "inegi")
    load()
    return seeded


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Baja California", "MX-BCN"),
        ("baja california", "MX-BCN"),
        ("Coahuila de Zaragoza", "MX-COA"),
        ("Coahuila", "MX-COA"),
        ("CDMX", "MX-CMX"),
        ("Atlantis", None),
    ],
)
def test_resolve_state(seeded: Session, name: str, code: str | None) -> None:
    hit = resolve_state(seeded, name)
    assert (hit[0] if hit else None) == code


def test_locality_precision(gazetteer: Session) -> None:
    r = geocode(
        gazetteer, place="Valentina", municipality="Municipio Sintético", state="Baja California"
    )
    assert r is not None
    assert (r.precision, r.admin2_code, r.admin1_code) == (1, "02999", "MX-BCN")
    assert (round(r.lon, 2), round(r.lat, 2)) == (-116.5, 31.7)


def test_municipality_uses_seat_not_polygon_centre(gazetteer: Session) -> None:
    r = geocode(gazetteer, place=None, municipality="municipio sintetico", state="BC")
    assert r is not None
    assert (r.precision, r.admin2_code) == (2, "02999")
    assert (round(r.lon, 2), round(r.lat, 2)) == (-116.6, 31.86)  # seat locality 0001


def test_place_named_like_its_municipality_resolves_to_seat(gazetteer: Session) -> None:
    r = geocode(gazetteer, place="Municipio Sintético", municipality=None, state="Baja California")
    assert r is not None
    assert (r.precision, r.admin2_code, round(r.lon, 2)) == (1, "02999", -116.6)


def test_state_precision_and_unresolved(gazetteer: Session) -> None:
    r = geocode(gazetteer, place="Nowhere", municipality=None, state="Sonora")
    assert r is not None
    assert (r.precision, r.admin1_code) == (3, "MX-SON")
    assert geocode(gazetteer, place="Valentina", municipality=None, state=None) is None
    assert (
        geocode(gazetteer, place="Bogotá", municipality=None, state=None, country="Colombia")
        is None
    )


@pytest.mark.parametrize(
    ("place", "municipality", "state", "expected"),
    [
        ("DeConcini Crossing, Port of Nogales", "Nogales", "Arizona", ("Nogales", 2, "US-AZ")),
        ("Juarez Lincoln Bridge", "Laredo", "Texas", ("Laredo", 2, "US-TX")),
        ("Calexico East port of entry", None, "California", ("Calexico East", 2, "US-CA")),
        ("San Clemente checkpoint", None, "California", ("California", 3, "US-CA")),
        (None, None, "TX", ("Texas", 3, "US-TX")),
        (None, None, "South Carolina", None),  # not a border state
    ],
)
def test_us_border_states_and_ports(
    seeded: Session,
    place: str | None,
    municipality: str | None,
    state: str,
    expected: tuple[str, int, str] | None,
) -> None:
    r = geocode(seeded, place=place, municipality=municipality, state=state, country="USA")
    assert ((r.matched, r.precision, r.admin1_code) if r else None) == expected
    if r is not None:
        assert r.country_iso3 == "USA"
        assert (r.node_id is not None) == (r.precision == 2)
