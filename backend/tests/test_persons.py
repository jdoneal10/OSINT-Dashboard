"""Person records (hard rule 3; ADR 0008, ADR 0013): cited claims, safeguards, matching,
replacement on re-extraction, and no uncited person. All names are synthetic."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Document,
    Person,
    PersonAttribute,
    PersonEvent,
    PersonOrganization,
)
from app.enrich import extract
from app.enrich.persons import clean_value, name_key
from tests.test_extract import GOOD, _resp, _run, doc_id  # noqa: F401 — doc_id is a fixture

# Person names must appear in the cited text to be stored (ADR 0013 amendment 1).
NAMED = (
    "Ramón Sintético Pérez", "Beto Sintético Gil", "Ana Sintética Ruiz", "Menor Sintético Uno",
    "Carl Synthetic Doe", "El Sintético", "La Ana", "Juan N", "+52 664 123 4567",
)  # fmt: skip


@pytest.fixture
def doc(seeded: Session, doc_id: int) -> int:  # noqa: F811 — test_extract's document fixture
    document = seeded.get_one(Document, doc_id)
    document.original_text = f"{document.original_text}\n" + "; ".join(NAMED)
    seeded.commit()
    return doc_id


def _person(name: str, **kw: Any) -> dict[str, Any]:
    return {
        "name": name,
        "aliases": [],
        "role": "member",
        "organization": None,
        "nationality": None,
        "us_nexus": False,
        "reported_minor": False,
        "statuses": [],
        "title": None,
        "events": [],
        "evidence": f"{name} fue detenido",
    } | kw


def _payload(*people: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(json.dumps(GOOD))
    payload["persons"] = list(people)
    return payload


def _attrs(session: Session, person: Person) -> set[tuple[str, str]]:
    rows = session.scalars(select(PersonAttribute).where(PersonAttribute.person_id == person.id))
    return {(a.attribute, a.value) for a in rows}


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Ramón Sintético Pérez", "ramon sintetico perez"),
        ("RAMÓN  sintético-PÉREZ", "ramon sintetico perez"),
        ("Ramón", None),  # one word: too thin to match
        ("Ramón N", None),  # Mexican placeholder surname
        ("José Luis N.", None),
    ],
)
def test_name_key_is_conservative(name: str, key: str | None) -> None:
    assert name_key(name) == key


@pytest.mark.parametrize(
    "value",
    ["+52 664 123 4567", "ramon@example.org", "https://example.org/x", "CURP ABCD", "1234567890"],
)
def test_contact_and_id_like_values_are_refused(value: str) -> None:
    assert clean_value(value) is None


def test_person_claims_are_cited_and_graded(seeded: Session, doc: int) -> None:
    _run(
        _resp(
            _payload(
                _person(
                    "Ramón Sintético Pérez",
                    aliases=["El Sintético"],
                    role="leader",
                    organization="Jalisco New Generation Cartel",
                    nationality="Mexico",
                    statuses=["arrested"],
                    title="plaza boss",
                    events=[{"event_index": 0, "role": "directed"}],
                )
            )
        )
    )
    person = seeded.scalars(select(Person)).one()
    assert (person.display_name, person.name_key) == (
        "Ramón Sintético Pérez",
        "ramon sintetico perez",
    )
    assert (person.us_person, person.disputed) == (False, False)
    assert _attrs(seeded, person) == {
        ("role", "leader"),
        ("alias", "El Sintético"),
        ("nationality", "Mexico"),
        ("status", "arrested"),
        ("title", "plaza boss"),
    }
    org = seeded.scalars(select(PersonOrganization)).one()
    ev = seeded.scalars(select(PersonEvent)).one()
    assert (org.role, ev.role) == ("leader", "directed")
    for row in [*seeded.scalars(select(PersonAttribute)), org, ev]:
        assert row.document_id == doc
        assert row.reported_on.isoformat() == "2026-11-10"
        assert (row.reliability, row.prompt_version) == ("B", extract.PROMPT_VERSION)
        assert 1 <= row.credibility <= 6
        assert row.evidence == "Ramón Sintético Pérez fue detenido"


def test_minors_and_contact_names_are_never_stored(seeded: Session, doc: int) -> None:
    _run(
        _resp(
            _payload(
                _person("Menor Sintético Uno", reported_minor=True),
                _person("+52 664 123 4567"),
                _person("Ana Sintética Ruiz", aliases=["ana@example.org", "La Ana"]),
            )
        )
    )
    person = seeded.scalars(select(Person)).one()
    assert person.display_name == "Ana Sintética Ruiz"
    assert ("alias", "La Ana") in _attrs(seeded, person)
    assert not any("@" in v for _, v in _attrs(seeded, person))


def test_us_nexus_flags_the_person(seeded: Session, doc: int) -> None:
    _run(_resp(_payload(_person("Carl Synthetic Doe", us_nexus=True, role="supplier"))))
    assert seeded.scalars(select(Person.us_person)).one() is True


def test_matching_joins_full_names_but_never_placeholders(seeded: Session, doc: int) -> None:
    payload = _payload(
        _person("Ramón Sintético Pérez"),
        _person("RAMÓN SINTÉTICO PÉREZ", statuses=["charged"]),
        _person("Juan N"),
        _person("Juan N"),
    )
    _run(_resp(payload))
    people = seeded.scalars(select(Person).order_by(Person.id)).all()
    assert [p.display_name for p in people] == ["Ramón Sintético Pérez", "Juan N", "Juan N"]
    assert ("status", "charged") in _attrs(seeded, people[0])


def test_reextraction_replaces_claims_and_drops_uncited_people(seeded: Session, doc: int) -> None:
    _run(_resp(_payload(_person("Ramón Sintético Pérez"), _person("Beto Sintético Gil"))))
    assert len(seeded.scalars(select(Person)).all()) == 2
    document = seeded.get_one(Document, doc)
    document.prompt_version, document.pipeline_status = "extract-v1", "relevant"
    seeded.commit()
    _run(_resp(_payload(_person("Ramón Sintético Pérez"))))
    seeded.expire_all()
    assert [p.display_name for p in seeded.scalars(select(Person))] == ["Ramón Sintético Pérez"]
    # Not relevant on a later pass: every claim from this document goes, and so does the person.
    document = seeded.get_one(Document, doc)
    document.prompt_version, document.pipeline_status = "extract-v1", "relevant"
    seeded.commit()
    _run(_resp({**_payload(), "relevant": False, "events": [], "seizures": []}))
    seeded.expire_all()
    assert seeded.scalars(select(Person)).all() == []


def test_event_index_out_of_range_is_ignored(seeded: Session, doc: int) -> None:
    _run(_resp(_payload(_person("Ramón Sintético Pérez",
                                events=[{"event_index": 7, "role": "perpetrator"}]))))  # fmt: skip
    assert seeded.scalars(select(PersonEvent)).all() == []
    assert seeded.scalars(select(Person)).one()


def test_database_refuses_an_uncited_claim(seeded: Session) -> None:
    person = Person(display_name="Synthetic Person", name_key="synthetic person")
    seeded.add(person)
    seeded.flush()
    with pytest.raises(IntegrityError, match="cited"):
        seeded.execute(
            PersonAttribute.__table__.insert().values(
                person_id=person.id, source_id=1, reported_on="2026-11-10", reliability="A",
                credibility=2, attribute="role", value="member",
            )
        )  # fmt: skip


def test_prompt_states_person_safeguards() -> None:
    rules = extract.RULES
    for phrase in (
        "NEVER list",
        "victims, bystanders, witnesses",
        "journalists, minors",
        "complicit_official",
        "Never record addresses, phone numbers, emails",
        "us_nexus",
    ):
        assert phrase in rules, phrase


# --------------------------------------------------------------------------- API


@pytest.fixture
def people(seeded: Session, doc: int) -> dict[str, int]:
    _run(
        _resp(
            _payload(
                _person(
                    "Ramón Sintético Pérez",
                    aliases=["El Sintético"],
                    role="leader",
                    organization="Jalisco New Generation Cartel",
                    events=[{"event_index": 0, "role": "directed"}],
                ),
                _person("Carl Synthetic Doe", us_nexus=True, role="supplier"),
            )
        )
    )
    return {p.display_name: p.id for p in seeded.scalars(select(Person))}


def test_api_hides_us_persons_by_default(client: Any, people: dict[str, int]) -> None:
    page = client.get("/persons").json()
    assert [p["display_name"] for p in page["items"]] == ["Ramón Sintético Pérez"]
    assert page["total"] == 1
    everyone = client.get("/persons", params={"include_us_persons": True}).json()
    assert {p["display_name"] for p in everyone["items"]} == set(people)
    us_id = people["Carl Synthetic Doe"]
    assert client.get(f"/persons/{us_id}").status_code == 404
    assert client.get(f"/persons/{us_id}", params={"include_us_persons": True}).json()["us_person"]


def test_api_detail_cites_every_claim(client: Any, people: dict[str, int]) -> None:
    detail = client.get(f"/persons/{people['Ramón Sintético Pérez']}").json()
    assert detail["roles"] == ["leader"]
    assert detail["organizations"] == ["Cartel de Jalisco Nueva Generacion"]  # canonical name
    kinds = {c["kind"] for c in detail["claims"]}
    assert kinds == {"role", "alias", "organization", "event"}
    for claim in detail["claims"]:
        cite = claim["citation"]
        assert cite["basis"] == "as reported"
        assert cite["document_id"] is not None
        assert cite["reported_on"] == "2026-11-10"
        assert cite["grade"][0] == "B"
        assert cite["grade"][1:].isdigit()


def test_api_search_matches_names_and_aliases(client: Any, people: dict[str, int]) -> None:
    for q in ("ramon", "Sintético Pérez", "el sintetico"):
        items = client.get("/persons", params={"q": q}).json()["items"]
        assert [p["display_name"] for p in items] == ["Ramón Sintético Pérez"], q
    assert client.get("/persons", params={"q": "carl"}).json()["items"] == []  # U.S. person


def test_owner_can_dispute_and_delete(client: Any, seeded: Session, people: dict[str, int]) -> None:
    pid = people["Ramón Sintético Pérez"]
    marked = client.put(f"/persons/{pid}/dispute", json={"disputed": True, "note": "wrong man"})
    assert marked.json()["disputed"] is True
    assert client.get(f"/persons/{pid}").json()["dispute_note"] == "wrong man"
    hidden = client.get("/persons", params={"include_disputed": False}).json()["items"]
    assert hidden == []
    cleared = client.put(f"/persons/{pid}/dispute", json={"disputed": False}).json()
    assert cleared["disputed"] is False
    assert client.delete(f"/persons/{pid}").status_code == 204
    assert client.get(f"/persons/{pid}").status_code == 404
    seeded.expire_all()
    for model in (PersonAttribute, PersonOrganization, PersonEvent):
        assert seeded.scalars(select(model).where(model.person_id == pid)).all() == []


# --------------------------------------------------------------------------- labels and eval


def test_person_labels_feed_the_phase3_safeguard_count(
    client: Any, seeded: Session, doc: int, people: dict[str, int]
) -> None:
    from app.enrich.evaluate import phase3, phase3_verdict  # noqa: PLC0415

    ramon, carl = people["Ramón Sintético Pérez"], people["Carl Synthetic Doe"]
    body = {"document_id": doc, "target_table": "persons", "target_id": ramon}
    ok = client.put("/labels", json=body | {"verdict": "correct"}).json()
    assert ok["prompt_version"] == extract.PROMPT_VERSION
    bad = body | {"target_id": carl, "verdict": "incorrect", "field": "excluded_category"}
    assert client.put("/labels", json=bad).status_code == 200
    # A person not extracted from this document cannot be labeled against it.
    assert (
        client.put("/labels", json=body | {"target_id": 999999, "verdict": "correct"}).status_code
        == 422
    )
    # The document detail lists this document's persons (U.S. persons flagged) for labeling.
    persons = client.get(f"/documents/{doc}").json()["persons"]
    assert {p["display_name"]: p["us_person"] for p in persons} == {
        "Ramón Sintético Pérez": False,
        "Carl Synthetic Doe": True,
    }
    from app.api.labels import _records_for  # noqa: PLC0415

    kinds = sorted(t for t, _ in _records_for(seeded, [doc])[doc])
    assert kinds == ["events", "persons", "persons", "seizures"]  # persons need labels too
    report = phase3(seeded, extract.PROMPT_VERSION)
    assert (report.persons.n, report.persons.correct) == (2, 1)
    assert report.violations == [(doc, carl, ["excluded_category"])]
    assert phase3_verdict(report).startswith("**FAIL**: 1 labeled person-safeguard")
