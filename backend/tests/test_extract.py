from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
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
