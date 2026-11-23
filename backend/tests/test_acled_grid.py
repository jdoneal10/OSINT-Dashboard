"""ACLED grid pass (ADR 0014). All notes are synthetic; no ACLED data is in this file."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, get_args

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ENERGY_INDICATORS, GRID_INTERACTIONS, Event, GridClassification, Source
from app.enrich import acled_grid
from app.enrich.llm.client import Gateway
from app.enrich.llm.schema import strict_schema
from tests.test_llm_batch import FakeBatches, ok

NOW = dt.datetime(2026, 11, 22, tzinfo=dt.UTC)
SABOTAGE = (
    "SYNTHETIC. Armed men linked to a criminal group burned an electrical substation in "
    "Pueblo Sintético during a roadblock, leaving the town without power."
)
PROTEST = "SYNTHETIC. Residents blocked a road to protest repeated power outages by the CFE."
UNRELATED = "SYNTHETIC. Gunmen attacked a bar in Pueblo Sintético."


def _resp(payload: dict[str, Any]) -> Any:
    from types import SimpleNamespace  # noqa: PLC0415

    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        stop_reason="end_turn", stop_details=None, model="claude-haiku-5-5",
        usage=SimpleNamespace(input_tokens=900, output_tokens=80,
                              cache_creation_input_tokens=0, cache_read_input_tokens=700),
        _request_id="req_x",
    )  # fmt: skip


def verdict(**kw: Any) -> dict[str, Any]:
    return {"kind": None, "indicators": [], "theft": None, "evidence": None} | kw


class Fake:
    def __init__(self, *replies: Any) -> None:
        from types import SimpleNamespace  # noqa: PLC0415

        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw: Any) -> Any:
        self.requests.append(kw)
        return self.replies.pop(0)


@pytest.fixture
def acled(seeded: Session) -> dict[str, int]:
    src = seeded.scalars(select(Source).where(Source.slug == "acled")).one()

    def ev(key: str, notes: str, day: int) -> int:
        e = Event(source_id=src.id, source_key=key, retrieved_at=NOW,
                  event_date=dt.date(2026, 11, day), event_type="Riots",
                  sub_event_type="Violent demonstration", description=notes,
                  admin1_name="Guerrero", admin2_name="Municipio Sintético",
                  attributes={"actor1": "Unidentified Armed Group (Mexico)"})  # fmt: skip
        seeded.add(e)
        seeded.flush()
        return e.id

    ids = {"sabotage": ev("SYN1", SABOTAGE, 3), "protest": ev("SYN2", PROTEST, 2),
           "unrelated": ev("SYN3", UNRELATED, 1)}  # fmt: skip
    seeded.commit()
    return ids


def test_categories_match_the_framework_lists() -> None:
    assert get_args(acled_grid.GridKind) == GRID_INTERACTIONS
    assert get_args(acled_grid.EnergyIndicator) == ENERGY_INDICATORS
    strict_schema(acled_grid.GridVerdict)  # the API's strict format accepts it


def test_verdict_rules() -> None:
    from pydantic import ValidationError  # noqa: PLC0415

    with pytest.raises(ValidationError):  # theft without its detail
        acled_grid.GridVerdict.model_validate(verdict(kind="theft", evidence="x"))
    with pytest.raises(ValidationError):  # a kind without a quote
        acled_grid.GridVerdict.model_validate(verdict(kind="utility_withdrawal"))
    acled_grid.GridVerdict.model_validate(verdict())


def test_candidates_match_grid_terms_only(acled: dict[str, int], session: Session) -> None:
    ids = list(session.scalars(acled_grid.candidates()))
    assert ids == [acled["sabotage"], acled["protest"]]  # newest first; the bar attack is out


def test_realtime_pass_stores_verdicts_and_provenance(
    acled: dict[str, int], session: Session
) -> None:
    fake = Fake(
        _resp(
            verdict(
                kind="deliberate_outage_or_sabotage",
                indicators=["outage_in_contested_area"],
                evidence="Armed men linked to a criminal group burned an electrical substation",
            )
        ),
        _resp(verdict()),
    )
    out = acled_grid.run_grid(gateway=Gateway(fake))
    assert (out["backlog"], out["done"]) == (2, 2)
    sent = fake.requests[0]["messages"][0]["content"]
    assert "ACLED event SYN1" in sent
    assert "Unidentified Armed Group" in sent
    session.expire_all()
    sab = session.get_one(Event, acled["sabotage"])
    assert sab.grid_interaction == "deliberate_outage_or_sabotage"
    assert sab.energy_indicators == ["outage_in_contested_area"]
    assert sab.energy_method is None
    row = session.get_one(GridClassification, acled["sabotage"])
    assert (row.status, row.llm_model, row.prompt_version) == (
        "done", "claude-haiku-5-5", acled_grid.PROMPT_VERSION)  # fmt: skip
    assert row.notes_sha256 == acled_grid.notes_hash(SABOTAGE)
    assert session.get_one(Event, acled["protest"]).grid_interaction is None
    # Nothing left to do on the next pass.
    assert acled_grid.run_grid(gateway=Gateway(Fake()))["backlog"] == 0


def test_theft_sets_the_energy_detail(acled: dict[str, int], session: Session) -> None:
    theft = {"method": "illegal_line_connection", "powered": ["crypto_mining"],
             "facilitator": "none_reported", "scale": None}  # fmt: skip
    fake = Fake(_resp(verdict(kind="theft", theft=theft, evidence="burned an electrical")))
    assert acled_grid.call_one(Gateway(fake), acled["sabotage"]) == "done"
    session.expire_all()
    ev = session.get_one(Event, acled["sabotage"])
    assert (ev.grid_interaction, ev.energy_method, ev.energy_powered) == (
        "theft", "illegal_line_connection", ["crypto_mining"])  # fmt: skip


def test_quote_not_in_the_notes_is_quarantined(acled: dict[str, int], session: Session) -> None:
    fake = Fake(_resp(verdict(kind="attack_on_utility_workers", evidence="CFE crew kidnapped")))
    assert acled_grid.call_one(Gateway(fake), acled["sabotage"]) == "quarantined"
    session.expire_all()
    assert session.get_one(Event, acled["sabotage"]).grid_interaction is None
    assert session.get_one(GridClassification, acled["sabotage"]).status == "quarantined"


def test_quote_may_use_the_actors_line_and_ellipses(
    acled: dict[str, int], session: Session
) -> None:
    ev = session.get_one(Event, acled["sabotage"])
    assert acled_grid.quote_found("Unidentified Armed Group (Mexico)", ev)
    assert acled_grid.quote_found(
        "Actors: Unidentified Armed Group (Mexico). Note: Armed men linked to a criminal group", ev
    )
    assert acled_grid.quote_found("Armed men linked ... leaving the town without power.", ev)
    assert acled_grid.quote_found(
        "Unidentified Armed Group (Mexico); Armed men linked to a criminal group}", ev
    )
    assert not acled_grid.quote_found("Armed men ... cut the cable", ev)
    assert not acled_grid.quote_found("...", ev)


def test_invalid_output_twice_is_quarantined(acled: dict[str, int], session: Session) -> None:
    bad = _resp(verdict(kind="theft", evidence="burned"))  # theft detail missing
    assert acled_grid.call_one(Gateway(Fake(bad, bad)), acled["sabotage"]) == "quarantined"
    session.expire_all()
    assert session.get_one(GridClassification, acled["sabotage"]).status == "quarantined"


def test_acled_edits_requeue_or_clear(acled: dict[str, int], session: Session) -> None:
    good = verdict(kind="deliberate_outage_or_sabotage", evidence="burned an electrical")
    acled_grid.call_one(Gateway(Fake(_resp(good))), acled["sabotage"])
    acled_grid.call_one(Gateway(Fake(_resp(verdict()))), acled["protest"])
    # ACLED rewrites one note (still about the grid) and the other (no longer about it).
    session.execute(update(Event).where(Event.id == acled["sabotage"])
                    .values(description=SABOTAGE + " Revised."))  # fmt: skip
    session.execute(update(Event).where(Event.id == acled["protest"])
                    .values(description=UNRELATED))  # fmt: skip
    session.commit()
    assert list(session.scalars(acled_grid.candidates())) == [acled["sabotage"]]
    session.execute(update(Event).where(Event.id == acled["sabotage"])
                    .values(description=UNRELATED))  # fmt: skip
    assert acled_grid.clear_stale(session) == 2
    session.commit()
    session.expire_all()
    assert session.get_one(Event, acled["sabotage"]).grid_interaction is None
    assert session.scalars(select(GridClassification)).all() == []


def test_backlog_goes_to_a_batch_and_is_collected(
    acled: dict[str, int], session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_batch_threshold", 2)
    fake = FakeBatches()
    out = acled_grid.run_grid(gateway=Gateway(fake))
    assert out["batched"] == 2
    assert {r["custom_id"] for r in fake.created[0]} == {
        f"event-{acled['sabotage']}", f"event-{acled['protest']}"}  # fmt: skip
    session.expire_all()
    rows = session.scalars(select(GridClassification)).all()
    assert {r.status for r in rows} == {"batched"}
    # Batched events are not submitted again while the batch runs.
    assert list(session.scalars(acled_grid.candidates())) == []
    fake.status = "ended"
    fake.outcomes = {
        f"event-{acled['sabotage']}": ok(_resp(verdict(kind="deliberate_outage_or_sabotage",
                                                       evidence="burned an electrical"))),
        f"event-{acled['protest']}": ok(_resp(verdict())),
    }  # fmt: skip
    out = acled_grid.run_grid(gateway=Gateway(fake))
    assert out["collected_ok"] == 2
    session.expire_all()
    assert session.get_one(Event, acled["sabotage"]).grid_interaction == (
        "deliberate_outage_or_sabotage")  # fmt: skip
    assert {r.status for r in session.scalars(select(GridClassification))} == {"done"}
