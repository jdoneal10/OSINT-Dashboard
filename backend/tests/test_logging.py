from __future__ import annotations

import pytest

from app.core.logging import REDACTED, redact


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        ("key sk-ant-api03-abcdefghijklmnop used", "sk-ant-api03-abcdefghijklmnop"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.x.y", "eyJhbGciOiJIUzI1NiJ9.x.y"),
        ("password=hunter2hunter2", "hunter2hunter2"),
        ("postgresql+psycopg://osint:topsecret@db:5432/osint", "topsecret"),
    ],
)
def test_redact_removes_secrets(raw: str, leak: str) -> None:
    cleaned = redact(raw)
    assert leak not in cleaned
    assert REDACTED in cleaned


def test_redact_leaves_ordinary_text() -> None:
    text = "loaded 10 areas for phase 1"
    assert redact(text) == text
