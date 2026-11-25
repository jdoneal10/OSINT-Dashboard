"""UxS labels and the separate Phase 3 gates (ADR 0009 amendment 1). All records are synthetic;
no ACLED data is in this file."""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Document, Event, Source, UxsClassification, UxsLabel, event_documents
from app.enrich import extract
from app.enrich.evaluate import Phase3Report, Precision, phase3, phase3_verdict

NOW = dt.datetime(2026, 11, 23, tzinfo=dt.UTC)


@pytest.fixture
def uxs(seeded: Session) -> dict[str, int]:
    acled = seeded.scalars(select(Source).where(Source.slug == "acled")).one()
    news = seeded.scalars(select(Source).where(Source.slug != "acled")).first()
    assert news is not None

    def ev(src: Source, key: str, activity: str | None, **kw: object) -> int:
        e = Event(source_id=src.id, source_key=key, retrieved_at=NOW,
                  event_date=dt.date(2026, 11, 2), event_type="Explosions/Remote violence",
                  description=f"SYNTHETIC note {key}", uxs_activity=activity,
                  uxs_platform="unknown" if activity else None, admin1_name="Michoacán",
                  attributes={"actor1": "Unidentified Armed Group (Mexico)", "evidence": "x"},
                  **kw)  # fmt: skip
        seeded.add(e)
        seeded.flush()
        return e.id

    ids = {
        "attack": ev(
            acled,
            "SYN1",
            "employment",
            uxs_missions=["attack"],
            uxs_payloads=["explosive_or_grenade"],
        ),
        "attack2": ev(acled, "SYN2", "employment", uxs_payloads=["none_reported"]),
        "seizure": ev(acled, "SYN3", "recovery_or_seizure", uxs_payloads=["none_reported"]),
        "nothing": ev(acled, "SYN4", None),
        "news": ev(news, "doc1:e0", "procurement_or_import", prompt_version=extract.PROMPT_VERSION),
        "news2": ev(news, "doc1:e1", "employment", prompt_version=extract.PROMPT_VERSION),
    }
    for key in ("attack", "attack2", "seizure", "nothing"):
        seeded.add(UxsClassification(event_id=ids[key], notes_sha256="0" * 64, status="done",
                                     evidence=f"quote {key}", prompt_version="uxs-v3"))  # fmt: skip
    doc = Document(source_id=news.id, source_key="https://example.org/u", retrieved_at=NOW,
                   title="Synthetic", original_text="SYNTHETIC", pipeline_status="extracted",
                   prompt_version=extract.PROMPT_VERSION)  # fmt: skip
    seeded.add(doc)
    seeded.flush()
    for key in ("news", "news2"):
        seeded.execute(event_documents.insert().values(event_id=ids[key], document_id=doc.id))
    seeded.commit()
    return ids | {"doc": doc.id}


def test_review_lists_uxs_events_interleaved_by_activity(
    uxs: dict[str, int], client: TestClient
) -> None:
    body = client.get("/uxs/review").json()
    assert body["size"] == 5  # the event with no UxS fields is not reviewed
    assert body["strata"] == {"employment": 3, "procurement_or_import": 1,
                              "recovery_or_seizure": 1}  # fmt: skip
    # One of each activity before the second and third employment records.
    assert sorted(i["stratum"] for i in body["items"][:3]) == [
        "employment", "procurement_or_import", "recovery_or_seizure"]  # fmt: skip
    by_id = {i["event_id"]: i for i in body["items"]}
    acled = by_id[uxs["attack"]]
    assert (acled["missions"], acled["payloads"], acled["evidence"], acled["prompt_version"]) == (
        ["attack"], ["explosive_or_grenade"], "quote attack", "uxs-v3")  # fmt: skip
    news = by_id[uxs["news"]]
    assert (news["prompt_version"], news["document_ids"]) == (extract.PROMPT_VERSION, [uxs["doc"]])
    assert len(client.get("/uxs/review?source=news").json()["items"]) == 2


def test_labels_freeze_the_verdict_and_validate_items(
    uxs: dict[str, int], client: TestClient, session: Session
) -> None:
    att = uxs["attack"]
    put = lambda **kw: client.put("/uxs/labels", json={"event_id": att} | kw)  # noqa: E731
    assert put(verdict="partial").status_code == 422  # must name the wrong items
    assert put(verdict="partial", wrong=["logistics"]).status_code == 422  # not in this verdict
    assert client.put("/uxs/labels", json={"event_id": uxs["nothing"], "verdict": "correct"}
                      ).status_code == 422  # fmt: skip
    lab = put(verdict="partial", wrong=["platform", "attack"]).json()
    assert (lab["judged_activity"], lab["judged_missions"], lab["prompt_version"]) == (
        "employment", ["attack"], "uxs-v3")  # fmt: skip
    assert lab["wrong"] == ["attack", "platform"]
    assert client.get("/uxs/review").json()["labeled"] == 1
    session.execute(update(Event).where(Event.id == att).values(uxs_platform="fpv"))
    session.commit()
    body = client.get("/uxs/review").json()
    assert next(i for i in body["items"] if i["event_id"] == att)["stale"] is True
    assert body["labeled"] == 0  # a stale label is to do again
    assert client.delete(f"/uxs/labels/{lab['id']}").status_code == 204


def test_database_requires_named_items_for_partial(uxs: dict[str, int], session: Session) -> None:
    def add(verdict: str, wrong: list[str]) -> None:
        lab = UxsLabel(
            event_id=uxs["seizure"],
            verdict=verdict,
            wrong=wrong,
            judged_activity="recovery_or_seizure",
            judged_platform="unknown",
        )
        session.add(lab)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    add("partial", [])
    add("correct", ["platform"])
    add("partial", ["not_an_item"])


def test_phase3_judges_uxs_and_energy_as_separate_samples(
    uxs: dict[str, int], client: TestClient, session: Session
) -> None:
    for key, verdict, wrong in (("attack", "partial", ["attack"]), ("attack2", "correct", []),
                                ("seizure", "incorrect", [])):  # fmt: skip
        body = {"event_id": uxs[key], "verdict": verdict, "wrong": wrong}
        assert client.put("/uxs/labels", json=body).status_code == 200
    # Record labels on the two news events: one wrong only outside the UxS fields, one with the
    # UxS fields wrong.
    for key, field in (("news", "location"), ("news2", "uxs")):
        body = {"document_id": uxs["doc"], "target_table": "events", "target_id": uxs[key],
                "verdict": "partial", "field": field}  # fmt: skip
        assert client.put("/labels", json=body).status_code == 200
    report = phase3(session, extract.PROMPT_VERSION)
    u = report.uxs
    assert (u.n, u.correct, u.partial, u.incorrect) == (5, 2, 2, 1)
    assert report.uxs_errors == Counter({"uxs": 1})
    assert report.energy.n == 0
    assert {k: (p.n, p.correct) for k, p in report.uxs_labels.by_source.items()} == {
        "acled": (3, 1)}  # fmt: skip
    items = {k: (p.n, p.correct) for k, p in report.uxs_labels.items.items()}
    assert items["mission: attack"] == (1, 0)  # named wrong
    assert items["activity: employment"] == (2, 2)
    assert items["activity: recovery_or_seizure"] == (1, 0)  # the label is "wrong"
    assert phase3_verdict(report).startswith("**INSUFFICIENT SAMPLE**: UxS 5 of 50, energy 0")
    # A UxS label on a news event replaces its record label in the sample.
    assert client.put("/uxs/labels", json={"event_id": uxs["news2"], "verdict": "correct"}
                      ).status_code == 200  # fmt: skip
    assert phase3(session, extract.PROMPT_VERSION).uxs.n == 5


def _p(correct: int, n: int = 50) -> Precision:
    return Precision(n=n, correct=correct, incorrect=n - correct)


def test_phase3_passes_only_when_both_samples_pass() -> None:
    def report(uxs: Precision, energy: Precision) -> Phase3Report:
        return Phase3Report(uxs, Counter(), energy, Counter(), Precision(), Counter(), [])

    assert phase3_verdict(report(_p(45), _p(44))).startswith("**PASS**: strict precision UxS")
    assert phase3_verdict(report(_p(45), _p(40))).startswith("**FAIL**")
    short = phase3_verdict(report(_p(45), _p(40, n=49)))
    assert short.startswith("**INSUFFICIENT SAMPLE**: energy 49 of 50")


def test_reextraction_keeps_uxs_labeled_documents(
    uxs: dict[str, int], client: TestClient, session: Session
) -> None:
    session.execute(update(Document).values(prompt_version="extract-v10"))
    session.commit()
    assert extract.mark_for_reextraction() == 1
    session.execute(update(Document).values(pipeline_status="extracted"))
    session.commit()
    assert client.put("/uxs/labels", json={"event_id": uxs["news"], "verdict": "correct"}
                      ).status_code == 200  # fmt: skip
    assert extract.mark_for_reextraction() == 0


def test_labels_judge_capabilities_and_older_labels_stay_current(
    uxs: dict[str, int], client: TestClient, session: Session
) -> None:
    # ADR 0009 amendment 2: a label saved with no capabilities stays current while the event
    # has none, and goes stale when the event gains one.
    att = uxs["attack"]
    lab = client.put("/uxs/labels", json={"event_id": att, "verdict": "correct"}).json()
    assert lab["judged_capabilities"] == []
    assert client.get("/uxs/review").json()["labeled"] == 1
    session.execute(update(Event).where(Event.id == att)
                    .values(uxs_capabilities=["coordinated_multi_uxs"]))  # fmt: skip
    session.commit()
    body = client.get("/uxs/review").json()
    item = next(i for i in body["items"] if i["event_id"] == att)
    assert (item["capabilities"], item["stale"], body["labeled"]) == (
        ["coordinated_multi_uxs"], True, 0)  # fmt: skip
    lab = client.put("/uxs/labels", json={"event_id": att, "verdict": "partial",
                                          "wrong": ["coordinated_multi_uxs"]}).json()  # fmt: skip
    assert (lab["judged_capabilities"], lab["wrong"]) == (
        ["coordinated_multi_uxs"], ["coordinated_multi_uxs"])  # fmt: skip
    assert client.get("/uxs/review").json()["labeled"] == 1
