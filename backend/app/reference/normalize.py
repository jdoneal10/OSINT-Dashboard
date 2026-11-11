"""Text normalization shared by alias matching (reference loader now, actor normalization later)."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def normalize_alias(text: str) -> str:
    """Case-fold, strip accents and punctuation, collapse whitespace.

    >>> normalize_alias("Cártel  de Jalisco Nueva Generación (CJNG)")
    'cartel de jalisco nueva generacion cjng'
    """
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _NON_WORD.sub(" ", no_accents.casefold())
    return _SPACE.sub(" ", cleaned).strip()
