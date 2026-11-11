from __future__ import annotations

import pytest

from app.reference.normalize import normalize_alias


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Cártel de Jalisco Nueva Generación", "cartel de jalisco nueva generacion"),
        ("  C.J.N.G. ", "c j n g"),
        ("Cárteles  Unidos", "carteles unidos"),
        ("Los Zetas / CDN", "los zetas cdn"),
    ],
)
def test_normalize_alias(raw: str, expected: str) -> None:
    assert normalize_alias(raw) == expected
