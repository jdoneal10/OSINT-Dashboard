"""Family details in model-written text (ADR 0013 amendment 2). All people are synthetic."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, Event
from app.enrich import text_guard
from tests.test_extract import _resp, _run, doc_id  # noqa: F401 — doc_id is a fixture
from tests.test_persons import _payload, _person

LISTED = ["Darío Sintético Vega", "El Grillo", "German N", "Grillo"]


@pytest.mark.parametrize(
    ("text", "stored"),
    [
        (
            "Darío Sintético Vega was held along with his cousin German N.",
            "Darío Sintético Vega was held along with German N.",
        ),
        (
            "Police held his cousin and second-in-command German N.",
            "Police held second-in-command German N.",
        ),
        (
            "Darío Sintético Vega, brother of leader Pedro Ficticio Uno, was sentenced.",
            "Darío Sintético Vega was sentenced.",
        ),
    ],
)
def test_kinship_is_cut_where_meaning_cannot_change(text: str, stored: str) -> None:
    assert text_guard.clean_text(text, LISTED) == stored


@pytest.mark.parametrize(
    "text",
    [
        "A court sentenced the brother of cartel leader Pedro Ficticio Uno.",
        "A court sentenced a brother of a Mexican cartel leader.",
        "He reportedly claimed to be a nephew of the late capo Pedro Ficticio Uno.",
        "A cousin of the target was detained.",
        "R1's brother was wounded.",
        "The group is led by the Ficticio Prueba brothers.",
        "Eight people were held, including relatives reported as operators.",
        "His brother José Ajeno Vega seeks a nomination.",
        "Darío Sintético Vega was found alongside his brother.",
        "He was arrested with his wife.",
        "Cartel leader Pedro Ficticio Uno got life while his brother and sons were released.",
    ],
)
def test_otherwise_the_sentence_is_withheld(text: str) -> None:
    assert text_guard.clean_text(text, LISTED) == text_guard.WITHHELD


def test_a_relative_is_never_turned_into_the_person() -> None:
    text = "A U.S. Army post closed. A court sentenced the brother of El Grillo. Roads reopened."
    assert text_guard.clean_text(text, LISTED) == "A U.S. Army post closed. Roads reopened."


@pytest.mark.parametrize(
    "text",
    [
        "A protest by mothers of disappeared persons on Álvaro Ficticio Avenue demanded progress.",
        "Families reported relatives missing after the capture of El Grillo.",
        "Relatives of musicians detained at a restaurant protested.",
        "Gunmen shot a man walking with his wife.",
        "An attack killed a local official and his wife.",
        "Parents occupied a school in Veracruz.",
        "An outage hit the Autódromo Hermanos Rodríguez.",
        "The Los Hermanos Prueba Gang moved fentanyl.",
        "La Familia Michoacana was indicted.",
        "Four members of one family, including a grandmother and her daughter, were killed.",
        "madres de desaparecidos en Culiacán marcharon",
    ],
)
def test_relatives_described_by_role_stay(text: str) -> None:
    assert text_guard.clean_text(text, LISTED) == text


@pytest.mark.parametrize(
    "quote",
    [
        "se identificó como sobrino del finado capo Pedro Ficticio Uno",
        "found with those of his brother José Ajeno Vega",
        "German N, su primo, y El Grillo",
    ],
)
def test_quotes_are_withheld_whole(quote: str) -> None:
    assert text_guard.clean_quote(quote, LISTED) is None


def test_extraction_stores_clean_text(seeded: Session, doc_id: int) -> None:  # noqa: F811
    doc = seeded.get_one(Document, doc_id)
    doc.original_text = f'{doc.original_text}\nDarío Sintético Vega y Germán "N".'
    seeded.commit()
    payload = _payload(_person("Darío Sintético Vega"), _person("Germán Inventado"))
    payload["summary_en"] = "Roads closed. Darío Sintético Vega fled with his brother."
    payload["events"][0]["description"] = "Police held his cousin Germán Inventado."
    payload["events"][0]["evidence"] = "su primo Germán Inventado Uno"
    _run(_resp(payload))
    seeded.expire_all()
    assert seeded.get_one(Document, doc_id).translated_text == "Roads closed."
    event = seeded.scalars(select(Event)).one()
    assert event.description == 'Police held Germán "N".'
    assert (event.attributes or {})["evidence"] is None
