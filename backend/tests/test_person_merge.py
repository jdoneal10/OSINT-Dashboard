"""Person fixes and reviewed merges (ADR 0013 amendment 1). All people are synthetic."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import person_matches
from app.db.models import Document, Label, Person, PersonAttribute, PersonMerge
from app.enrich import identity, person_guard, person_repair
from app.enrich.persons import alias_forms, name_key
from tests.test_extract import _resp, _run, doc_id  # noqa: F401 — doc_id is a fixture
from tests.test_persons import _payload, _person

FULL = "Darío de la Vega Sintético"
OTHER = "Darío de la Vega Ficticio"
TEXT = (
    f'{FULL}, alias "El Grillo". {OTHER}. Darío "N", alias "El Grillo". Germán «N». '
    'Juan "N". Ana "La Nube" Prueba Modelo. El Grillo. Lucía Prueba Modelo.'
)


@pytest.fixture
def docs(seeded: Session, doc_id: int) -> list[int]:  # noqa: F811
    first = seeded.get_one(Document, doc_id)
    first.original_text = f"{first.original_text}\n{TEXT}"
    out = [first.id]
    for n in (2, 3):
        d = Document(source_id=first.source_id, source_key=f"https://full.example.org/p{n}",
                     retrieved_at=first.retrieved_at, published_at=first.published_at,
                     title=f"Doc {n}", original_text=first.original_text,
                     pipeline_status="skipped")  # fmt: skip
        seeded.add(d)
        seeded.flush()
        out.append(d.id)
    first.pipeline_status = "skipped"
    seeded.commit()
    return out


def extract_doc(session: Session, document_id: int, *people: dict[str, Any], **top: Any) -> None:
    doc = session.get_one(Document, document_id)
    doc.pipeline_status, doc.prompt_version = "relevant", "extract-v1"
    session.commit()
    _run(_resp(_payload(*people) | top))
    session.expire_all()


def people(session: Session) -> list[Person]:
    return list(session.scalars(select(Person).order_by(Person.id)))


# --------------------------------------------------------------------------- 1: names


@pytest.mark.parametrize(
    ("name", "body", "stored"),
    [
        ("Germán Inventado", "detención de Germán “N”, alias", "Germán “N”"),
        ("German Prestado", "cayó Germán N, segundo", "Germán N"),
        ("Ana Prueba Modelo", 'cayó Ana "La Nube" Prueba Modelo', "Ana Prueba Modelo"),
        ("Pedro Inventado", "nadie con ese nombre", None),
        ("Germán Inventado", "Germán huyó.\nN de la R", None),
    ],
)
def test_a_name_the_text_lacks_is_never_stored(name: str, body: str, stored: str | None) -> None:
    assert person_guard.supported_name(name, body) == stored


def test_extraction_stores_only_supported_names_and_aliases(
    seeded: Session, docs: list[int]
) -> None:
    extract_doc(
        seeded,
        docs[0],
        _person("Germán Inventado", aliases=["El Inexistente"]),
        _person("Pedro Inventado"),
    )
    (person,) = people(seeded)
    assert person.display_name == "Germán «N»"
    assert "alias" not in set(seeded.scalars(select(PersonAttribute.attribute)))


# --------------------------------------------------------------------------- 2 and 7: rule 3


@pytest.mark.parametrize(
    ("title", "stored"),
    [
        ("Primo y segundo al mando", "segundo al mando"),
        ("cousin and second-in-command", "second-in-command"),
        ("cuñado", None),
        ("jefe de plaza", "jefe de plaza"),
    ],
)
def test_titles_lose_family_details(title: str, stored: str | None) -> None:
    assert person_guard.clean_title(title) == stored


@pytest.mark.parametrize(
    "quote",
    [
        "Germán N, su primo y segundo al mando",
        "led the group since his father's capture",
        "his son took over",
        "Security Secretary Omar Sintético Uno identified the leader",
        "el secretario de Seguridad, Omar Sintético Uno, lo señaló",
        "Omar Sintético Uno, el secretario, lo señaló",
        "el secuestro del periodista Luis Ficticio",
    ],
)
def test_unsafe_quotes_are_withheld(quote: str) -> None:
    assert person_guard.safe_quote(quote, ["Germán N"]) is None


@pytest.mark.parametrize(
    "quote",
    [
        'encabezado por Heraclio "N" (a) "Tío Lako"',
        "integrante del grupo Familia Michoacana",
        "detenidos en la Sierra Madre",
        "la Secretaría de Marina lo detuvo",
        "el alcalde Vicente Sintético Dos fue detenido",  # he is the listed person
        "conocido como Primo",
    ],
)
def test_ordinary_quotes_are_kept(quote: str) -> None:
    assert person_guard.safe_quote(quote, ["Vicente Sintético Dos", "Primo"]) == quote


def test_extraction_applies_the_safeguards(seeded: Session, docs: list[int]) -> None:
    extract_doc(
        seeded, docs[0],
        _person(FULL, title="primo y jefe de plaza", evidence=f"{FULL}, su primo"),
    )  # fmt: skip
    rows = seeded.scalars(select(PersonAttribute)).all()
    assert ("title", "jefe de plaza") in {(r.attribute, r.value) for r in rows}
    assert {r.evidence for r in rows} == {None}


# --------------------------------------------------------------------------- 3 and 4: matching


@pytest.mark.parametrize(
    ("name", "key"),
    [
        (FULL, "dario de la vega sintetico"),
        ("Fausto Isidro", None),  # two given names
        ("Chapo Isidro", None),
        ("El Chapo de Ejemplo Uno", None),  # a nickname
        ("Juan de Dios", None),
        ("Martín Prueba-Modelo", "martin prueba modelo"),
    ],
)
def test_match_keys(name: str, key: str | None) -> None:
    assert name_key(name) == key


def test_full_names_with_particles_join(seeded: Session, docs: list[int]) -> None:
    for d in docs:
        extract_doc(seeded, d, _person(FULL))
    assert len(people(seeded)) == 1


def test_alias_forms_read_hashtags() -> None:
    assert "topo" in alias_forms("#ElTopo") & alias_forms("El Topo")


# --------------------------------------------------------------------------- 5 and 6


def test_sources_count_outlets_not_articles(client: Any, seeded: Session, docs: list[int]) -> None:
    for d in docs:
        extract_doc(seeded, d, _person(FULL))
    (row,) = client.get("/persons").json()["items"]
    assert (row["n_sources"], row["n_documents"]) == (1, 3)


def test_reextraction_keeps_id_dispute_merge_and_label(
    client: Any, seeded: Session, docs: list[int]
) -> None:
    extract_doc(seeded, docs[0], _person('Darío "N"', aliases=["El Grillo"]), _person('Juan "N"'))
    extract_doc(seeded, docs[1], _person(FULL, aliases=["El Grillo"]))
    masked, juan, full = [p.id for p in people(seeded)]
    body = {"document_id": docs[0], "target_table": "persons", "target_id": masked}
    assert client.put("/labels", json=body | {"verdict": "correct"}).status_code == 200
    assert client.put(f"/persons/{juan}/dispute", json={"disputed": True}).status_code == 200
    merged = {"person_ids": [masked, full], "primary_id": full}
    assert client.post("/persons/merges", json=merged).status_code == 200

    # The same article, read again: one name in another form, matched through the alias.
    extract_doc(seeded, docs[0], _person('Juan "N"'), _person("Darío N", aliases=["El Grillo"]))
    assert [p.id for p in people(seeded)] == [masked, juan, full]
    assert seeded.get_one(Person, juan).disputed is True
    assert identity.load(seeded).root_of[masked] == full
    label = seeded.scalars(select(Label).where(Label.target_table == "persons")).one()
    assert (label.target_id, label.document_id) == (masked, docs[0])


def test_removing_a_middle_record_keeps_the_rest_linked(seeded: Session, docs: list[int]) -> None:
    extract_doc(seeded, docs[0], _person('Juan "N"'))
    extract_doc(seeded, docs[1], _person('Juan "N"'))
    extract_doc(seeded, docs[2], _person('Juan "N"'))
    a, b, c = [p.id for p in people(seeded)]
    identity.merge(seeded, [a, b], b)
    identity.merge(seeded, [b, c], c)
    seeded.commit()
    extract_doc(seeded, docs[1], relevant=False, events=[], seizures=[])  # b loses its citation
    ids = identity.load(seeded)
    assert sorted(ids.people) == [a, c]
    assert ids.root_of[a] == c


# --------------------------------------------------------------------------- merges


@pytest.fixture
def trio(seeded: Session, docs: list[int]) -> tuple[int, int, int]:
    extract_doc(seeded, docs[0], _person(FULL, aliases=["El Grillo"]))
    extract_doc(seeded, docs[1], _person('Darío "N"', aliases=["El Grillo"]))
    extract_doc(seeded, docs[2], _person('Juan "N"'))
    a, b, c = [p.id for p in people(seeded)]
    return a, b, c


def test_merge_reads_as_one_and_undo_restores(
    client: Any, seeded: Session, trio: tuple[int, int, int]
) -> None:
    full, masked, juan = trio
    claims = {(a.id, a.person_id) for a in seeded.scalars(select(PersonAttribute))}
    body = {"person_ids": [full, masked], "primary_id": full}
    assert client.post("/persons/merges", json=body).json()["n_records"] == 2
    assert {p["id"] for p in client.get("/persons").json()["items"]} == {full, juan}
    detail = client.get(f"/persons/{masked}").json()  # any record id resolves to the identity
    assert detail["id"] == full
    assert detail["display_name"] == FULL
    # No source is made to say a name it did not publish.
    said = {c["record_id"]: c["reported_name"] for c in detail["claims"]}
    assert said == {full: FULL, masked: 'Darío "N"'}
    seeded.expire_all()
    assert {(a.id, a.person_id) for a in seeded.scalars(select(PersonAttribute))} == claims

    (link,) = [r["merge_id"] for r in detail["records"] if r["merge_id"]]
    assert client.post(f"/persons/merges/{link}/undo").status_code == 204
    assert client.get("/persons").json()["total"] == 3
    assert client.get(f"/persons/{masked}").json()["id"] == masked
    assert client.post(f"/persons/merges/{link}/undo").status_code == 404
    assert seeded.scalars(select(PersonMerge)).one()  # the history stays


def test_merged_records_can_be_found_by_either_name(
    client: Any, trio: tuple[int, int, int]
) -> None:
    full, _, juan = trio
    client.post("/persons/merges", json={"person_ids": [full, juan], "primary_id": full})
    assert [p["id"] for p in client.get("/persons", params={"q": "juan"}).json()["items"]] == [full]


def test_a_merge_with_a_us_person_is_hidden_everywhere(
    client: Any, seeded: Session, docs: list[int], trio: tuple[int, int, int]
) -> None:
    full, masked, _ = trio
    seeded.get_one(Person, masked).us_person = True
    seeded.commit()
    hidden = client.get("/persons/merge-suggestions").json()
    assert (hidden["items"], hidden["hidden_us_persons"]) == ([], 1)
    client.post("/persons/merges", json={"person_ids": [full, masked], "primary_id": full})
    assert full not in {p["id"] for p in client.get("/persons").json()["items"]}
    assert client.get("/persons", params={"q": "dario"}).json()["items"] == []
    assert client.get(f"/persons/{full}").status_code == 404
    assert client.get(f"/persons/{masked}").status_code == 404
    assert client.get(f"/persons/{full}", params={"include_us_persons": True}).json()["us_person"]
    (shown,) = client.get(f"/documents/{docs[0]}").json()["persons"]
    assert shown["us_person"] is True


def test_not_the_same_is_remembered(
    client: Any, seeded: Session, trio: tuple[int, int, int]
) -> None:
    full, masked, juan = trio
    assert len(client.get("/persons/merge-suggestions").json()["items"]) == 1
    body = {"person_id": full, "other_ids": [masked]}
    assert client.post("/persons/distinctions", json=body).status_code == 204
    assert client.get("/persons/merge-suggestions").json()["items"] == []
    merge = {"person_ids": [full, masked], "primary_id": full}
    assert client.post("/persons/merges", json=merge).status_code == 409
    # It also holds through a third record merged with one side.
    client.post("/persons/merges", json={"person_ids": [masked, juan], "primary_id": masked})
    merge = {"person_ids": [full, masked], "primary_id": full}
    assert client.post("/persons/merges", json=merge).status_code == 409
    (decision,) = client.get(f"/persons/{full}").json()["distinct_from"]
    assert client.delete(f"/persons/distinctions/{decision['id']}").status_code == 204
    assert client.post("/persons/merges", json=merge).status_code == 200


def test_stale_and_circular_merges_are_refused(client: Any, trio: tuple[int, int, int]) -> None:
    full, masked, juan = trio
    assert client.post(
        "/persons/merges", json={"person_ids": [full, masked], "primary_id": full}
    ).is_success
    for ids, primary in (([full, masked], masked), ([masked, juan], juan), ([juan, 9999], juan)):
        body = {"person_ids": ids, "primary_id": primary}
        assert client.post("/persons/merges", json=body).status_code == 409
    body = {"person_id": full, "other_ids": [masked]}
    assert client.post("/persons/distinctions", json=body).status_code == 409


def test_dispute_and_delete_act_on_the_whole_identity(
    client: Any, seeded: Session, trio: tuple[int, int, int]
) -> None:
    full, masked, juan = trio
    client.post("/persons/merges", json={"person_ids": [full, masked], "primary_id": full})
    assert client.put(f"/persons/{masked}/dispute", json={"disputed": True}).json()["disputed"]
    seeded.expire_all()
    assert [p.disputed for p in people(seeded)] == [True, True, False]
    assert client.delete(f"/persons/{full}").status_code == 204
    seeded.expire_all()
    assert [p.id for p in people(seeded)] == [juan]


# --------------------------------------------------------------------------- suggestions


def ticked(session: Session) -> list[dict[int, bool]]:
    found = person_matches.suggest(session, identity.load(session))
    return [{c.person_id: c.selected for c in s.candidates} for s in found]


def test_alias_and_context_make_a_ticked_suggestion(
    seeded: Session, trio: tuple[int, int, int]
) -> None:
    full, masked, _ = trio
    assert ticked(seeded) == [{full: True, masked: True}]


def test_a_common_masked_name_is_never_pre_ticked(seeded: Session, docs: list[int]) -> None:
    # Regression: identical "Juan N" names once counted as a shared alias.
    org = "Jalisco New Generation Cartel"
    for d in docs:
        extract_doc(seeded, d, _person('Juan "N"', aliases=['Juan "N"'], organization=org))
    (group,) = ticked(seeded)
    assert sorted(group.values()) == [False, False, True]  # only the record being reviewed


def test_a_shared_alias_never_joins_two_different_full_names(
    seeded: Session, docs: list[int]
) -> None:
    extract_doc(seeded, docs[0], _person(FULL, aliases=["El Grillo"]))
    extract_doc(seeded, docs[1], _person("Lucía Prueba Modelo", aliases=["El Grillo"]))
    assert ticked(seeded) == []


def test_two_records_in_one_article_are_not_pre_ticked(seeded: Session, docs: list[int]) -> None:
    extract_doc(
        seeded, docs[0],
        _person(FULL, aliases=["El Grillo"]), _person('Darío "N"', aliases=["El Grillo"]),
    )  # fmt: skip
    (suggestion,) = person_matches.suggest(seeded, identity.load(seeded))
    other = suggestion.candidates[1]
    assert other.selected is False
    assert other.warning == "named separately in the same article"


def test_exact_names_marked_distinct_stop_auto_joining(seeded: Session, docs: list[int]) -> None:
    extract_doc(seeded, docs[0], _person(FULL))
    twin = Person(display_name=FULL, name_key=name_key(FULL))
    seeded.add(twin)
    seeded.flush()
    original = seeded.scalars(select(PersonAttribute)).first()
    assert original is not None
    skip = ("id", "person_id", "created_at", "updated_at")
    copy = {c.name: getattr(original, c.name) for c in original.__table__.c if c.name not in skip}
    seeded.add(PersonAttribute(person_id=twin.id, **copy))
    seeded.flush()
    identity.mark_distinct(seeded, original.person_id, [twin.id])
    seeded.commit()
    extract_doc(seeded, docs[1], _person(FULL))
    assert len(people(seeded)) == 3  # the owner decides which Darío this is


# --------------------------------------------------------------------------- repair


def test_repair_fixes_stored_records_once_and_keeps_labels(
    seeded: Session, docs: list[int]
) -> None:
    extract_doc(seeded, docs[0], _person(FULL, title="jefe"), _person("Germán «N»"))
    full, masked = people(seeded)
    full.name_key = None
    masked.display_name = "Germán Inventado"
    for a in seeded.scalars(select(PersonAttribute)):
        if a.attribute == "title":
            a.value = "primo y jefe"
        a.evidence = "su primo"
    seeded.add(Label(document_id=docs[0], target_table="persons", target_id=masked.id,
                     verdict="correct"))  # fmt: skip
    seeded.commit()

    report = person_repair.repair(seeded)
    assert [pid for pid, _ in report.names] == [masked.id]
    assert (full.name_key, masked.display_name) == ("dario de la vega sintetico", "Germán «N»")
    rows = seeded.scalars(select(PersonAttribute)).all()
    assert ("title", "jefe") in {(a.attribute, a.value) for a in rows}
    assert {a.evidence for a in rows} == {None}
    assert seeded.scalars(select(Label)).one().target_id == masked.id
    assert person_repair.repair(seeded) == person_repair.Report()
