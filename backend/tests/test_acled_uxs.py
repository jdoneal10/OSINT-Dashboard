"""ACLED UxS pass (ADR 0009 amendment 1). All notes are synthetic; no ACLED data is in this file."""

from __future__ import annotations

import datetime as dt
from typing import Any, get_args

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    UXS_ACTIVITIES,
    UXS_CAPABILITIES,
    UXS_MISSIONS,
    UXS_PAYLOADS,
    UXS_PLATFORMS,
    Event,
    Source,
    UxsClassification,
)
from app.enrich import acled_uxs
from app.enrich.extract import UxsActivity, UxsCapability, UxsMission, UxsPayload, UxsPlatform
from app.enrich.llm.client import Gateway
from app.enrich.llm.schema import strict_schema
from tests.test_acled_grid import Fake, _resp
from tests.test_llm_batch import FakeBatches, ok

NOW = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)
ATTACK = (
    "SYNTHETIC. Members of a criminal group used drones to launch explosives at houses in "
    "Pueblo Sintético. No casualties."
)
POLICE = "SYNTHETIC. State police used a drone to search for a missing hiker near Pueblo."
UNIVERSITY = "SYNTHETIC. Students of the UAS protested in front of the rector's office."
DETAIL = {"activity": "employment", "platform": "unknown", "missions": ["attack"],
          "payloads": ["explosive_or_grenade"]}  # fmt: skip


def verdict(**kw: Any) -> dict[str, Any]:
    return {"uxs": None, "evidence": None} | kw


@pytest.fixture
def acled(seeded: Session) -> dict[str, int]:
    src = seeded.scalars(select(Source).where(Source.slug == "acled")).one()

    def ev(key: str, notes: str, day: int) -> int:
        e = Event(source_id=src.id, source_key=key, retrieved_at=NOW,
                  event_date=dt.date(2026, 11, day), event_type="Explosions/Remote violence",
                  sub_event_type="Air/drone strike", description=notes,
                  admin1_name="Michoacán", admin2_name="Municipio Sintético",
                  attributes={"actor1": "Unidentified Armed Group (Mexico)"})  # fmt: skip
        seeded.add(e)
        seeded.flush()
        return e.id

    ids = {"attack": ev("SYN1", ATTACK, 3), "police": ev("SYN2", POLICE, 2),
           "university": ev("SYN3", UNIVERSITY, 1)}  # fmt: skip
    seeded.commit()
    return ids


def test_categories_match_the_framework_lists() -> None:
    assert get_args(UxsActivity) == UXS_ACTIVITIES
    assert get_args(UxsPlatform) == UXS_PLATFORMS
    assert get_args(UxsMission) == UXS_MISSIONS
    assert get_args(UxsPayload) == UXS_PAYLOADS
    assert get_args(UxsCapability) == UXS_CAPABILITIES
    strict_schema(acled_uxs.UxsVerdict)  # the API's strict format accepts it


def test_a_verdict_needs_a_quote() -> None:
    from pydantic import ValidationError  # noqa: PLC0415

    with pytest.raises(ValidationError):
        acled_uxs.UxsVerdict.model_validate(verdict(uxs=DETAIL))
    acled_uxs.UxsVerdict.model_validate(verdict())


def test_candidates_match_drone_terms_only(acled: dict[str, int], session: Session) -> None:
    # Newest first; "UAS" (the Autonomous University of Sinaloa) is not a candidate.
    assert list(session.scalars(acled_uxs.candidates())) == [acled["attack"], acled["police"]]


def test_realtime_pass_stores_the_uxs_fields_and_provenance(
    acled: dict[str, int], session: Session
) -> None:
    fake = Fake(
        _resp(verdict(uxs=DETAIL, evidence="used drones to launch explosives at houses")),
        _resp(verdict()),
    )
    out = acled_uxs.run_uxs(gateway=Gateway(fake))
    assert (out["backlog"], out["done"]) == (2, 2)
    sent = fake.requests[0]["messages"][0]["content"]
    assert "ACLED event SYN1" in sent
    assert "Unidentified Armed Group" in sent
    session.expire_all()
    ev = session.get_one(Event, acled["attack"])
    assert (ev.uxs_activity, ev.uxs_platform, ev.uxs_missions, ev.uxs_payloads) == (
        "employment", "unknown", ["attack"], ["explosive_or_grenade"])  # fmt: skip
    row = session.get_one(UxsClassification, acled["attack"])
    assert (row.status, row.llm_model, row.prompt_version, row.evidence) == (
        "done", "claude-haiku-5-5", acled_uxs.PROMPT_VERSION,
        "used drones to launch explosives at houses")  # fmt: skip
    assert session.get_one(Event, acled["police"]).uxs_activity is None
    assert session.get_one(UxsClassification, acled["police"]).evidence is None
    assert acled_uxs.run_uxs(gateway=Gateway(Fake()))["backlog"] == 0


def test_quote_not_in_the_notes_is_quarantined(acled: dict[str, int], session: Session) -> None:
    fake = Fake(_resp(verdict(uxs=DETAIL, evidence="a drone dropped a grenade on a patrol")))
    assert acled_uxs.call_one(Gateway(fake), acled["attack"]) == "quarantined"
    session.expire_all()
    assert session.get_one(Event, acled["attack"]).uxs_activity is None
    assert session.get_one(UxsClassification, acled["attack"]).status == "quarantined"


def test_acled_edits_requeue_or_clear(acled: dict[str, int], session: Session) -> None:
    good = verdict(uxs=DETAIL, evidence="used drones to launch explosives")
    acled_uxs.call_one(Gateway(Fake(_resp(good))), acled["attack"])
    session.execute(update(Event).where(Event.id == acled["attack"])
                    .values(description=ATTACK + " Revised."))  # fmt: skip
    session.commit()
    assert acled["attack"] in set(session.scalars(acled_uxs.candidates()))
    session.execute(update(Event).where(Event.id == acled["attack"])
                    .values(description=UNIVERSITY))  # fmt: skip
    assert acled_uxs.clear_stale(session) == 1
    session.commit()
    session.expire_all()
    assert session.get_one(Event, acled["attack"]).uxs_activity is None
    assert session.scalars(select(UxsClassification)).all() == []


def test_backlog_goes_to_a_batch_and_is_collected(
    acled: dict[str, int], session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "llm_batch_threshold", 2)
    fake = FakeBatches()
    assert acled_uxs.run_uxs(gateway=Gateway(fake))["batched"] == 2
    session.expire_all()
    assert {r.status for r in session.scalars(select(UxsClassification))} == {"batched"}
    assert list(session.scalars(acled_uxs.candidates())) == []
    fake.status = "ended"
    fake.outcomes = {
        f"event-{acled['attack']}": ok(_resp(verdict(uxs=DETAIL, evidence="used drones"))),
        f"event-{acled['police']}": ok(_resp(verdict())),
    }
    assert acled_uxs.run_uxs(gateway=Gateway(fake))["collected_ok"] == 2
    session.expire_all()
    assert session.get_one(Event, acled["attack"]).uxs_activity == "employment"
    assert {r.status for r in session.scalars(select(UxsClassification))} == {"done"}


MULTI = (
    "SYNTHETIC. Gunmen of a criminal group flew three explosive drones together over Pueblo "
    "Sintético and dropped grenades. No casualties."
)


def test_v4_verdicts_stay_current_and_only_capability_notes_requeue_on_request(
    acled: dict[str, int], session: Session
) -> None:
    # ADR 0009 amendment 2: uxs-v5 adds capabilities without a blanket re-run.
    src = session.scalars(select(Source).where(Source.slug == "acled")).one()
    multi = Event(source_id=src.id, source_key="SYN4", retrieved_at=NOW,
                  event_date=dt.date(2026, 11, 4), event_type="Explosions/Remote violence",
                  description=MULTI, attributes={})  # fmt: skip
    seized = Event(source_id=src.id, source_key="SYN5", retrieved_at=NOW,
                   event_date=dt.date(2026, 11, 5), event_type="Strategic developments",
                   description="SYNTHETIC. Five drones of a criminal group were seized in "
                   "Pueblo Sintético.", attributes={})  # fmt: skip
    session.add_all([multi, seized])
    session.commit()
    seizure = DETAIL | {"activity": "recovery_or_seizure", "missions": [], "payloads": []}
    acled_uxs.run_uxs(gateway=Gateway(Fake(
        _resp(verdict(uxs=seizure, evidence="Five drones of a criminal group were seized")),
        _resp(verdict(uxs=DETAIL, evidence="flew three explosive drones together")),
        _resp(verdict()), _resp(verdict()),
    )))  # fmt: skip
    session.execute(update(UxsClassification).values(prompt_version="uxs-v4"))
    session.commit()
    assert list(session.scalars(acled_uxs.candidates())) == []  # v4 is still current

    listed = acled_uxs.requeue_capabilities(session, apply=False)
    # "three explosive drones" in an attack; "Five drones" seized cannot show a capability.
    assert [key for _, key, _ in listed] == ["SYN4"]
    assert list(session.scalars(acled_uxs.candidates())) == []  # listing changes nothing
    acled_uxs.requeue_capabilities(session, apply=True)
    session.commit()
    assert list(session.scalars(acled_uxs.candidates())) == [multi.id]

    detail = DETAIL | {"capabilities": ["coordinated_multi_uxs"]}
    fake = Fake(_resp(verdict(uxs=detail, evidence="flew three explosive drones together")))
    assert acled_uxs.run_uxs(gateway=Gateway(fake))["done"] == 1
    session.expire_all()
    assert session.get_one(Event, multi.id).uxs_capabilities == ["coordinated_multi_uxs"]
    assert session.get_one(UxsClassification, multi.id).prompt_version == "uxs-v5"
    assert acled_uxs.requeue_capabilities(session, apply=False) == []
