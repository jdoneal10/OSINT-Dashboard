"""Grid labels (ADR 0014 step 6). All records are synthetic; no ACLED data is in this file."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    Event,
    GridClassification,
    GridLabel,
    Source,
    event_documents,
)
from app.enrich import extract
from app.enrich.evaluate import phase3, phase3_verdict

NOW = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)


@pytest.fixture
def grid(seeded: Session) -> dict[str, int]:
    acled = seeded.scalars(select(Source).where(Source.slug == "acled")).one()
    news = seeded.scalars(select(Source).where(Source.slug != "acled")).first()
    assert news is not None

    def ev(src: Source, key: str, kind: str | None, indicators: list[str], **kw: object) -> int:
        e = Event(source_id=src.id, source_key=key, retrieved_at=NOW,
                  event_date=dt.date(2026, 11, 2), event_type="Riots",
                  description=f"SYNTHETIC note {key}", grid_interaction=kind,
                  energy_indicators=indicators, admin1_name="Guerrero",
                  attributes={"actor1": "Unidentified Armed Group (Mexico)", "evidence": "x"},
                  **kw)  # fmt: skip
        seeded.add(e)
        seeded.flush()
        return e.id

    ids = {
        "sabotage": ev(
            acled, "SYN1", "deliberate_outage_or_sabotage", ["outage_in_contested_area"]
        ),
        "fuel": ev(acled, "SYN2", None, ["fuel_theft"]),
        "fuel2": ev(acled, "SYN3", None, ["fuel_theft"]),
        "nothing": ev(acled, "SYN4", None, []),
        "news": ev(news, "doc1:e0", "attack_on_utility_workers", [], prompt_version="extract-v11"),
    }
    for key in ("sabotage", "fuel", "fuel2", "nothing"):
        seeded.add(GridClassification(event_id=ids[key], notes_sha256="0" * 64,
                                      status="done", evidence=f"quote {key}",
                                      prompt_version="grid-v3"))  # fmt: skip
    doc = Document(source_id=news.id, source_key="https://example.org/a", retrieved_at=NOW,
                   title="Synthetic", original_text="SYNTHETIC", pipeline_status="extracted",
                   prompt_version="extract-v10")  # fmt: skip
    seeded.add(doc)
    seeded.flush()
    seeded.execute(event_documents.insert().values(event_id=ids["news"], document_id=doc.id))
    seeded.commit()
    return ids | {"doc": doc.id}


def test_review_lists_grid_outputs_interleaved_by_stratum(
    grid: dict[str, int], client: TestClient
) -> None:
    body = client.get("/grid/review").json()
    assert body["size"] == 4  # the event with no kind or indicator is not reviewed
    assert body["strata"] == {"attack_on_utility_workers": 1,
                              "deliberate_outage_or_sabotage": 1, "fuel_theft": 2}  # fmt: skip
    strata = [i["stratum"] for i in body["items"]]
    # One of each stratum before the second fuel-theft record.
    assert sorted(strata[:3]) == ["attack_on_utility_workers", "deliberate_outage_or_sabotage",
                                  "fuel_theft"]  # fmt: skip
    by_id = {i["event_id"]: i for i in body["items"]}
    acled = by_id[grid["sabotage"]]
    assert (acled["evidence"], acled["prompt_version"]) == ("quote sabotage", "grid-v3")
    assert acled["actors"] == ["Unidentified Armed Group (Mexico)"]
    news = by_id[grid["news"]]
    assert (news["prompt_version"], news["document_ids"]) == ("extract-v11", [grid["doc"]])
    assert [i["event_id"] for i in client.get("/grid/review?source=news").json()["items"]] == [
        grid["news"]
    ]


def test_labels_freeze_the_verdict_and_validate_items(
    grid: dict[str, int], client: TestClient, session: Session
) -> None:
    sab = grid["sabotage"]
    put = lambda **kw: client.put("/grid/labels", json={"event_id": sab} | kw)  # noqa: E731
    assert put(verdict="partial").status_code == 422  # must name the wrong items
    assert put(verdict="partial", wrong=["fuel_theft"]).status_code == 422  # not in this verdict
    assert client.put("/grid/labels", json={"event_id": grid["nothing"], "verdict": "correct"}
                      ).status_code == 422  # fmt: skip
    r = put(verdict="partial", wrong=["kind"], note="side effect of a truck fire")
    assert r.status_code == 200
    lab = r.json()
    assert (lab["judged_kind"], lab["judged_indicators"], lab["prompt_version"]) == (
        "deliberate_outage_or_sabotage", ["outage_in_contested_area"], "grid-v3")  # fmt: skip
    # Saving again replaces the label; a whole-record verdict drops the named items.
    lab2 = put(verdict="correct", wrong=["kind"]).json()
    assert (lab2["id"], lab2["verdict"], lab2["wrong"]) == (lab["id"], "correct", [])
    assert client.get("/grid/review").json()["labeled"] == 1
    item = next(i for i in client.get("/grid/review").json()["items"] if i["event_id"] == sab)
    assert (item["label"]["verdict"], item["stale"]) == ("correct", False)
    # The event is reclassified: the label is stale.
    session.execute(update(Event).where(Event.id == sab).values(energy_indicators=[]))
    session.commit()
    body = client.get("/grid/review").json()
    item = next(i for i in body["items"] if i["event_id"] == sab)
    assert item["stale"] is True
    assert body["labeled"] == 0  # a stale label is to do again
    assert client.delete(f"/grid/labels/{lab['id']}").status_code == 204


def test_database_requires_named_items_for_partial(grid: dict[str, int], session: Session) -> None:
    session.add(GridLabel(event_id=grid["fuel"], verdict="partial", wrong=[]))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(GridLabel(event_id=grid["fuel"], verdict="correct", wrong=["power_outage"]))
    with pytest.raises(IntegrityError):
        session.flush()


def test_phase3_counts_current_grid_labels(
    grid: dict[str, int], client: TestClient, session: Session
) -> None:
    for key, verdict, wrong in (("sabotage", "partial", ["kind"]), ("fuel", "correct", []),
                                ("fuel2", "incorrect", []), ("news", "correct", [])):  # fmt: skip
        body = {"event_id": grid[key], "verdict": verdict, "wrong": wrong}
        assert client.put("/grid/labels", json=body).status_code == 200
    report = phase3(session, extract.PROMPT_VERSION)
    assert (report.priority.n, report.priority.correct) == (4, 2)
    assert {k: (p.n, p.correct) for k, p in report.grid.by_source.items()} == {
        "acled": (3, 1), "news": (1, 1)}  # fmt: skip
    items = {k: (p.n, p.correct) for k, p in report.grid.items.items()}
    assert items == {
        "deliberate_outage_or_sabotage": (1, 0),  # the kind was named wrong
        "outage_in_contested_area": (1, 1),  # the indicator on the same event was right
        "fuel_theft": (2, 1),
        "attack_on_utility_workers": (1, 1),
    }
    assert phase3_verdict(report).startswith("**INSUFFICIENT SAMPLE**: 4 of 50")
    # A reclassified event's label is left out until it is labeled again.
    session.execute(update(Event).where(Event.id == grid["fuel2"]).values(energy_indicators=[],
                    grid_interaction="infrastructure_theft"))  # fmt: skip
    session.commit()
    report = phase3(session, extract.PROMPT_VERSION)
    assert (report.priority.n, report.grid.stale) == (3, 1)


def test_reextraction_keeps_grid_labeled_documents(
    grid: dict[str, int], client: TestClient, session: Session
) -> None:
    assert extract.mark_for_reextraction() == 1  # the news document (extract-v10)
    session.execute(update(Document).values(pipeline_status="extracted"))
    session.commit()
    body = {"event_id": grid["news"], "verdict": "correct", "wrong": []}
    assert client.put("/grid/labels", json=body).status_code == 200
    assert extract.mark_for_reextraction() == 0
