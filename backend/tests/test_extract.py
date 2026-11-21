from __future__ import annotations

import datetime as dt
import json
import shutil
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Actor, Document, Event, Seizure, Source, actor_events
from app.enrich import extract
from app.enrich.llm.client import Gateway
from app.ingest.feeds import load_feeds, sync_sources
from app.reference.inegi_load import load as load_inegi

INEGI = Path(__file__).parent / "fixtures" / "inegi"
NEWS = Path(__file__).parent / "fixtures" / "news" / "feeds.yaml"


def _resp(payload: dict[str, Any] | str) -> Any:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        stop_details=None,
        model="claude-haiku-5-5",
        usage=SimpleNamespace(
            input_tokens=3000, output_tokens=600, cache_creation_input_tokens=0,
            cache_read_input_tokens=2500,
        ),
        _request_id="req_x",
    )  # fmt: skip


class Fake:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw: Any) -> Any:
        self.requests.append(kw)
        return self.replies.pop(0)


LOC = {"place": "Valentina", "municipality": "Municipio Sintético", "state": "Baja California",
       "country": "Mexico"}  # fmt: skip
GOOD = {
    "relevant": True,
    "summary_en": "Synthetic clash between a known cartel and an unknown cell.",
    "events": [
        {
            "event_type": "Battles",
            "sub_event_type": "Armed clash",
            "event_date": "2026-11-09",
            "date_precision": "day",
            "location": LOC,
            "fatalities": 3,
            "injured": None,
            "perpetrators": ["Jalisco New Generation Cartel", "Los Sintéticos"],
            "targets": ["hombres armados"],
            "description": "Gunmen clashed; three died.",
            "evidence": "dejó tres muertos",
            "border_threat": None,
            "uxs": None,
            "energy_theft": None,
        }
    ],
    "seizures": [
        {
            "seizure_date": None,
            "location": {**LOC, "place": None},
            "substance": "fentanyl",
            "chemicals": [],
            "quantity": 12.5,
            "unit": "kg",
            "seizing_agency": "SEMAR",
            "description": "Fentanyl seized.",
        }
    ],
    "organizations": [
        {"name": "Jalisco New Generation Cartel", "org_type": "cartel"},
        {"name": "Los Sintéticos", "org_type": "gang"},
        {"name": "hombres armados", "org_type": "other"},
    ],
}


@pytest.fixture
def doc_id(seeded: Session, raw_dir: Path) -> int:
    shutil.copytree(INEGI, raw_dir / "reference" / "inegi")
    load_inegi()
    sync_sources(seeded, load_feeds(NEWS))
    src = seeded.scalars(select(Source).where(Source.slug == "test-fulltext")).one()
    doc = Document(
        source_id=src.id,
        source_key="https://full.example.org/x",
        source_url="https://full.example.org/x",
        retrieved_at=dt.datetime.now(dt.UTC),
        published_at=dt.datetime(2026, 11, 10, tzinfo=dt.UTC),
        title="Enfrentamiento sintético",
        original_text="TEXTO SINTÉTICO. Un enfrentamiento dejó tres muertos.",
        language="es",
        pipeline_status="relevant",
    )
    seeded.add(doc)
    seeded.commit()
    return doc.id


def _run(*replies: Any) -> tuple[dict[str, int], Fake]:
    fake = Fake(*replies)
    return extract.run_extract(gateway=Gateway(fake)), fake


def test_extraction_stores_geocoded_records_and_links(seeded: Session, doc_id: int) -> None:
    counts, fake = _run(_resp(GOOD))
    assert counts == {"extracted": 1, "not_relevant": 0, "quarantined": 0, "events": 1,
                      "seizures": 1}  # fmt: skip
    seeded.expire_all()
    doc = seeded.get_one(Document, doc_id)
    assert (doc.pipeline_status, doc.prompt_version, doc.llm_model) == (
        "extracted", extract.PROMPT_VERSION, "claude-haiku-5-5")  # fmt: skip
    assert doc.translated_text.startswith("Synthetic clash")

    ev = seeded.scalars(select(Event)).one()
    assert (ev.event_type, ev.fatalities, ev.event_date, ev.time_precision) == (
        "Battles", 3, dt.date(2026, 11, 9), 1)  # fmt: skip
    assert (ev.geo_precision, ev.admin1_code, ev.admin2_code) == (1, "MX-BCN", "02999")
    assert ev.source_key == f"doc{doc_id}:e0"
    assert ev.confidence is not None  # baseline from the outlet's reliability (B)

    links = dict(
        seeded.execute(
            select(Actor.canonical_name, actor_events.c.role)
            .join(actor_events, actor_events.c.actor_id == Actor.id)
            .where(actor_events.c.event_id == ev.id)
        ).all()
    )
    assert links["Cartel de Jalisco Nueva Generacion"] == "perpetrator"  # alias match
    assert links["Los Sintéticos"] == "perpetrator"  # new criminal group, created
    assert "hombres armados" not in links  # generic phrase -> no actor
    new = seeded.scalars(select(Actor).where(Actor.canonical_name == "Los Sintéticos")).one()
    assert new.sources[0]["publisher"] == "Test Full-Text Outlet"  # cited to the news source

    sz = seeded.scalars(select(Seizure)).one()
    assert (sz.substance, sz.quantity, sz.unit, sz.seizure_date) == (
        "fentanyl", 12.5, "kg", dt.date(2026, 11, 10))  # fmt: skip

    req = fake.requests[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["output_config"]["effort"] == "low"


def test_not_relevant_per_haiku(seeded: Session, doc_id: int) -> None:
    payload = {**GOOD, "relevant": False, "events": [], "seizures": [], "organizations": []}
    counts, _ = _run(_resp(payload))
    assert counts["not_relevant"] == 1
    seeded.expire_all()
    assert seeded.get_one(Document, doc_id).pipeline_status == "filtered_out"


def test_invalid_output_quarantines_document(seeded: Session, doc_id: int) -> None:
    counts, _ = _run(_resp("{}"), _resp("not json"))
    assert counts["quarantined"] == 1
    seeded.expire_all()
    assert seeded.get_one(Document, doc_id).pipeline_status == "quarantined"


def test_reextraction_replaces_records(seeded: Session, doc_id: int) -> None:
    _run(_resp(GOOD))
    with seeded.begin():
        seeded.get_one(Document, doc_id).pipeline_status = "relevant"  # new prompt version
    _run(_resp(GOOD))
    assert seeded.scalar(select(func.count()).select_from(Event)) == 1
    assert seeded.scalar(select(func.count()).select_from(Seizure)) == 1


def test_system_block_is_deterministic_and_cacheable(seeded: Session) -> None:
    a, b = extract.build_system(seeded), extract.build_system(seeded)
    assert a == b
    assert "The only individuals you may name are leaders of criminal organizations" in a
    assert "Cartel de Sinaloa" in a
    assert len(a) > 2500  # comfortably above the 512-token cache minimum


def test_border_threat_categories_match_the_database() -> None:
    from typing import get_args  # noqa: PLC0415

    from app.db.models import BORDER_THREATS  # noqa: PLC0415

    assert get_args(extract.BorderThreat) == BORDER_THREATS


def test_border_threat_is_stored(seeded: Session, doc_id: int) -> None:
    payload = json.loads(json.dumps(GOOD))
    payload["events"][0]["border_threat"] = "gunfire"
    _run(_resp(payload))
    assert seeded.scalars(select(Event.border_threat)).one() == "gunfire"


def test_prompt_states_threat_only_rule() -> None:
    assert "NEVER record the number" in extract.RULES
    assert "border_threat" in extract.RULES


# --------------------------------------------------------------------------- UxS and energy (v7)


def test_v7_categories_match_the_database() -> None:
    from typing import get_args  # noqa: PLC0415

    from app.db import models  # noqa: PLC0415

    pairs = (
        (extract.UxsPlatform, models.UXS_PLATFORMS),
        (extract.UxsMission, models.UXS_MISSIONS),
        (extract.UxsPayload, models.UXS_PAYLOADS),
        (extract.UxsActivity, models.UXS_ACTIVITIES),
        (extract.EnergyMethod, models.ENERGY_METHODS),
        (extract.EnergyPowered, models.ENERGY_POWERED),
        (extract.EnergyFacilitator, models.ENERGY_FACILITATORS),
    )
    for literal, values in pairs:
        assert get_args(literal) == values


def _event(**kw: Any) -> dict[str, Any]:
    return {**GOOD["events"][0], **kw}


def test_uxs_and_energy_theft_are_stored(seeded: Session, doc_id: int) -> None:
    payload = json.loads(json.dumps(GOOD))
    payload["events"] = [
        _event(
            event_type="Explosions/Remote violence",
            uxs={
                "activity": "employment",
                "platform": "fpv",
                "missions": ["attack", "attack", "surveillance"],
                "payloads": ["explosive_or_grenade"],
            },
        ),
        _event(
            event_type="Strategic developments",
            fatalities=None,
            energy_theft={
                "method": "illegal_line_connection",
                "powered": ["crypto_mining"],
                "facilitator": "none_reported",
                "scale": "300 mining rigs",
            },
        ),
    ]
    _run(_resp(payload))
    drone, power = seeded.scalars(select(Event).order_by(Event.source_key)).all()
    assert (drone.uxs_activity, drone.uxs_platform) == ("employment", "fpv")
    assert drone.uxs_missions == ["attack", "surveillance"]  # duplicates dropped, order kept
    assert drone.uxs_payloads == ["explosive_or_grenade"]
    assert (drone.energy_method, drone.energy_powered) == (None, [])
    assert (power.energy_method, power.energy_facilitator) == (
        "illegal_line_connection",
        "none_reported",
    )
    assert (power.energy_powered, power.energy_scale) == (["crypto_mining"], "300 mining rigs")
    assert (power.uxs_activity, power.uxs_missions) == (None, [])
    assert {e.prompt_version for e in (drone, power)} == {"extract-v7"}


def test_unknown_uxs_category_is_rejected(seeded: Session, doc_id: int) -> None:
    payload = json.loads(json.dumps(GOOD))
    payload["events"][0]["uxs"] = {"activity": "employment", "platform": "jetpack",
                                   "missions": [], "payloads": []}  # fmt: skip
    _run(_resp(payload), _resp(payload))  # invalid twice: quarantined, nothing stored
    assert seeded.scalars(select(Event)).all() == []


def test_database_rejects_categories_outside_the_framework(seeded: Session, doc_id: int) -> None:
    from sqlalchemy import update  # noqa: PLC0415
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    _run(_resp(GOOD))
    for values in (
        {"uxs_activity": "employment"},  # platform missing
        {"uxs_activity": "employment", "uxs_platform": "fpv", "uxs_missions": ["joyride"]},
        {"energy_method": "meter_bypass"},  # facilitator missing
        {
            "energy_method": "meter_bypass",
            "energy_facilitator": "none_reported",
            "energy_powered": ["casino"],
        },
    ):
        with pytest.raises(IntegrityError):
            seeded.execute(update(Event).values(**values))
        seeded.rollback()


def test_prompt_states_priorities_and_v7_rules() -> None:
    rules = extract.RULES
    assert rules.index("unmanned systems") < rules.index("human smuggling")
    for phrase in ("11. uxs.", "12. energy_theft.", "Police or military drones",
                   "never infer a site", "Never name the person", "drones; cash"):  # fmt: skip
        assert phrase in rules, phrase


# --------------------------------------------------------------------------- seizures (v6)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("fentanyl", "fentanyl"),
        ("Methamphetamine", "methamphetamine"),
        ("cristal", "methamphetamine"),
        ("marihuana", "marijuana"),
        ("weapons", "firearms"),
        ("cartuchos", "ammunition"),
        ("unspecified illicit substance", "unidentified drug"),
        ("suspected narcotics", "unidentified drug"),
        ("alleged illicit substance", "unidentified drug"),
        ("unknown substance", "unidentified drug"),
        ("drugs (unspecified)", "unidentified drug"),
        ("precursor chemicals", "precursor chemicals"),
        ("drug precursors", "drug precursors"),  # never folded into a drug
        ("contraband cigarettes", "contraband cigarettes"),
    ],
)
def test_canonical_substance(raw: str, canonical: str) -> None:
    assert extract.canonical_substance(raw) == canonical


def _seizure(substance: str, quantity: float | None, unit: str | None, **kw: Any) -> dict[str, Any]:
    return {"seizure_date": None, "location": {**LOC, "place": None}, "substance": substance,
            "chemicals": [], "quantity": quantity, "unit": unit, "seizing_agency": None,
            "description": "Synthetic seizure.", **kw}  # fmt: skip


def test_mixed_load_is_stored_one_record_per_item(seeded: Session, doc_id: int) -> None:
    # Synthetic mixed load: a rifle, two magazines with 31 rounds, half a kilo of "cristal",
    # packages of an unidentified substance, and a lab's precursor drums.
    payload = json.loads(json.dumps(GOOD))
    payload["seizures"] = [
        _seizure("weapons", 1, "units"),
        _seizure("magazines", 2, "units"),
        _seizure("ammunition", 31, "units"),
        _seizure("cristal", 0.5, "kg"),
        _seizure("suspected narcotics", None, "packages"),
        _seizure("precursor chemicals", 400, "l", chemicals=["benzyl chloride"]),
    ]
    counts, _ = _run(_resp(payload))
    assert counts["seizures"] == 6
    rows = seeded.execute(
        select(Seizure.substance, Seizure.quantity, Seizure.unit, Seizure.chemical_class)
        .order_by(Seizure.source_key)
    ).all()  # fmt: skip
    assert [tuple(r) for r in rows] == [
        ("firearms", 1, "units", None),
        ("magazines", 2, "units", None),
        ("ammunition", 31, "units", None),
        ("methamphetamine", 0.5, "kg", None),
        ("unidentified drug", None, "packages", None),
        ("precursor chemicals", 400, "l", "benzyl chloride"),
    ]


def test_seizure_units_include_packages_and_doses() -> None:
    from typing import get_args  # noqa: PLC0415

    assert {"packages", "doses"} <= set(get_args(extract.SeizureUnit))
    with pytest.raises(ValidationError, match="unit"):
        extract.ExtractedSeizure.model_validate(_seizure("cocaine", 3, "bricks"))


def test_prompt_states_seizure_rules() -> None:
    rules = extract.RULES
    for rule in (
        "S1. Not seizures",
        "S2. One record per item",
        "S3. substance",
        "S4. Precursor vs product",
        "S5. quantity and unit",
        "S6. seizure_date",
    ):
        assert rule in rules
    assert "unidentified drug" in rules
    assert "never give a combined total" in rules
    # Event rules are untouched by the seizure work.
    assert "4. Event types (use exactly these)" in rules
    assert "9. border_threat." in rules


@pytest.mark.parametrize(
    ("substance", "quantity", "unit", "low"),
    [
        # Weapons, ammunition, explosives, precursors and cash: never low priority.
        ("firearms", "1", "units", False),
        ("ammunition", "31", "units", False),
        ("explosives", "3", "units", False),
        ("precursor chemicals", "5", "l", False),
        ("cash", "1000", "units", False),
        # Fentanyl: low below 1 kg.
        ("fentanyl", "0.9", "kg", True),
        ("fentanyl", "1", "kg", False),
        ("fentanyl", "3", "lb", False),  # 1.36 kg
        ("fentanyl", "5000", "pills", True),  # about 0.5 kg
        ("fentanyl", "20000", "pills", False),  # about 2 kg
        # Other drugs: low below 10 kg, any unit.
        ("methamphetamine", "0.5", "kg", True),
        ("cocaine", "8", "kg", True),
        ("methamphetamine", "1.1", "lb", True),
        ("cristal", "500", "g", True),  # synonym folded first
        ("cocaine", "10", "kg", False),
        ("marijuana", "34", "lb", False),  # 15.4 kg
        ("methamphetamine", "1000", "l", False),
        ("unidentified drug", "4470", "doses", True),  # retail amounts
        # No measurable amount: kept visible, it could be a large load.
        ("unidentified drug", None, "packages", False),
        ("cocaine", None, None, False),
        ("cocaine", "24", "other", False),
        # Contraband goods: low priority at any size.
        ("contraband cigarettes", "31856000", "units", True),
    ],
)
def test_seizure_low_priority(substance: str, quantity: str | None, unit: str | None,
                              low: bool) -> None:  # fmt: skip
    amount = Decimal(quantity) if quantity is not None else None
    assert extract.seizure_low_priority(substance, amount, unit) is low


def test_priority_is_stored_per_record(seeded: Session, doc_id: int) -> None:
    # Synthetic operation: rifles plus a small drug amount. Only the drug is low priority.
    payload = json.loads(json.dumps(GOOD))
    payload["seizures"] = [_seizure("firearms", 3, "units"), _seizure("cocaine", 8, "kg")]
    _run(_resp(payload))
    rows = seeded.execute(
        select(Seizure.substance, Seizure.low_priority).order_by(Seizure.source_key)
    ).all()
    assert [tuple(r) for r in rows] == [("firearms", False), ("cocaine", True)]


def test_reprioritize_backfills_stored_seizures(seeded: Session, doc_id: int) -> None:
    payload = json.loads(json.dumps(GOOD))
    payload["seizures"] = [_seizure("cocaine", 8, "kg")]
    _run(_resp(payload))
    with seeded.begin():
        seeded.scalars(select(Seizure)).one().low_priority = False  # as before migration 0012
    assert extract.reprioritize() == 1
    seeded.expire_all()
    assert seeded.scalars(select(Seizure.low_priority)).one() is True
    assert extract.reprioritize() == 0  # idempotent
