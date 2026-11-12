from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Place, ReferenceArea
from app.reference.inegi_load import load, place_key

FIX = Path(__file__).parent / "fixtures" / "inegi"


def test_place_key_drops_bracketed_type_suffixes() -> None:
    assert place_key("Valentina [Rancho]") == "valentina"
    assert place_key("Heroica Nogales (Nogales)") == "heroica nogales"
    assert place_key("Ciudad Juárez") == "ciudad juarez"


def test_load_is_idempotent_and_coded(seeded: Session, raw_dir: Path) -> None:
    shutil.copytree(FIX, raw_dir / "reference" / "inegi")
    first = load()
    second = load()
    assert first == second == {"municipalities": 1, "localities": 2, "states": 1}

    area = seeded.scalars(select(ReferenceArea).where(ReferenceArea.slug == "mx-mun-02999")).one()
    assert (area.area_type, area.admin1_code, area.admin2_code, area.phase) == (
        "admin2",
        "MX-BCN",
        "02999",
        2,
    )
    assert area.sources[0]["publisher"] == "INEGI"

    places = {p.code: p for p in seeded.scalars(select(Place))}
    assert set(places) == {"02", "02999", "029990001", "029990042"}
    rancho = places["029990042"]
    assert (rancho.name, rancho.name_normalized, rancho.population, rancho.urban) == (
        "Valentina [Rancho]",
        "valentina",
        None,
        False,
    )
    assert rancho.admin2_code == "02999"
    assert places["02999"].point is not None  # municipality representative point
    assert seeded.scalar(select(func.count()).select_from(Place)) == 4
