"""Related-story headlines never reach stored article text. All text is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.articles import page_text
from app.ingest.related import strip_related

STRAY = "Lo procesan por un delito sintético en otro municipio"
# An article page's element structure with every letter masked: "c" is the article, "s" a
# headline card for another story. Without the prune the card becomes the first line.
PAGE = Path(__file__).parent / "fixtures" / "news" / "quadratin-related.html"


def test_related_widget_is_pruned_from_the_page() -> None:
    text = page_text(PAGE.read_text())
    assert text is not None
    assert "cccccccc" in text
    assert "sssss" not in text


@pytest.mark.parametrize(
    "label",
    [
        "Te puede interesar leer:", "Te puede interesar:", "Te puede interesar>",
        "Te podría interesar:", "Puede interesarle:", "Te sugerimos:", "Le sugerimos leer:",
        "Sugerimos leer:", "Te recomendamos:", "Le recomendamos leer:", "Puedes leer:",
        "Puede leer:", "Puede leer también:", "Podrías leer:", "Debes leer:", "No dejes de leer:",
        "Nota relacionada:", "Nota recomendada:", "Relacionado:", "Relacionada:",
        "Sigue leyendo:", "Entérate:", "SEE ALSO:", "LEER TAMBIÉN:", "Leer también:",
        "No deje de leer:", "Siga leyendo:", "Debería leer:", "Tiene que leer:", "Lee:",
        "Nota sugerida:", "Sugerido:", "Prodría interesarle:", "Podría interesarle:",
        "Más en policiaca:", "Más en Sinaloa:", "Más de la LMP:",
    ],
)  # fmt: skip
def test_labeled_related_lines_are_dropped(label: str) -> None:
    assert strip_related(f"Uno.\n{label} {STRAY}\nDos.") == "Uno.\nDos."


def test_lists_under_a_label_are_dropped() -> None:
    text = "Uno.\nRead more:\n- Other story\n- Another story\nDos.\n- A real bullet"
    assert strip_related(text) == "Uno.\nDos.\n- A real bullet"
    text = "Uno.\nRead More Updates\nNovember 12, 2026 – Other story\nDos."  # noqa: RUF001
    assert strip_related(text) == "Uno.\nDos."


def test_link_paths_standing_in_for_headlines_are_dropped() -> None:
    path = "/mexico/2026/11/20/detienen-a-persona-sintetica-en-otro-municipio/"
    assert strip_related(f"Uno.\n{path}\nDos.") == "Uno.\nDos."


@pytest.mark.parametrize(
    "line",
    [
        "#Entérate | Un hombre fue detenido",
        "También puedes seguir estas medidas antes de un sismo: prepara un plan",
        "Les recomendamos mantenerse en contacto con su aerolínea",
        "El homicidio está relacionado: hay tres detenidos",
        "For more information visit: the agency page",
        "Source: La Razón",
        "Más de la mitad: 60% de los casos siguen abiertos",
        "Más en concreto, la fiscalía investiga dos casos",
        "Lee el comunicado completo de la fiscalía.",
        "El material está en /mexico/2026/11/20/nota/ según el expediente",
        "Read more about the indictment in the court record.",
    ],
)
def test_ordinary_lines_stay(line: str) -> None:
    assert strip_related(line) == line
