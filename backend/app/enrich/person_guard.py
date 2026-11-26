"""Storage-time checks on extracted person data (hard rule 3; ADR 0013 amendment 1).

The prompt states these rules, and these checks enforce what can be checked without a model:

- a name or alias is stored only if the cited text contains it;
- kinship is a family detail: it is cut from titles, and a quote carrying it is withheld;
- a quote naming someone by a non-criminal role (an official, journalist or victim) who is
  not a listed person is withheld.

A withheld quote leaves the claim cited to its document. The checks are word lists and
patterns: a bare third-party name with no role word beside it still needs the owner's eye.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.reference.normalize import normalize_alias

PLACEHOLDERS = frozenset({"n", "nn", "x", "xx"})

_WORD = re.compile(r"\w+")
# A short quoted segment: a nickname or "N" ("Fausto 'El Chapo' Isidro").
_QUOTED = re.compile(r"[\"“«‘][^\"“”«»‘’\n]{1,30}[\"”»’]|(?<!\w)'[^'\n]{1,30}'(?!\w)")  # noqa: RUF001
_KIN = re.compile(
    r"\b("
    r"prim[oa]s?|herman[oa]s?|medi[oa] herman[oa]|hij[oa]s?|padres?|(?<!sierra )madre|pap[áa]|"
    r"mam[áa]|espos[oa]s?|sobrin[oa]s?|tí[oa]s?|cuñad[oa]s?|yerno|nuera|suegr[oa]s?|novi[oa]|"
    r"pareja sentimental|familiar(es)?|"
    r"cousins?|brothers?|sisters?|daughters?|fathers?|mothers?|parents|wife|husband|nephews?|"
    r"nieces?|uncles?|aunts?|girlfriend|boyfriend|relatives?|\w+-in-law|"
    r"(his|her|their|whose|'s|’s) sons?|sons? of"  # noqa: RUF001
    r")\b",
    re.IGNORECASE,
)
_PART = re.compile(r"\s*[,;/&]\s*|\s+(?:y|and)\s+")
_ROLE = (
    r"(?i:\b(?:secretar(?:y|io|ia)|governor|gobernador|gobernadora|prosecutor|vicefiscal|"
    r"fiscal|president|presidente|presidenta|mayor|alcalde|alcaldesa|senator|senador|senadora|"
    r"diputad[oa]|ambassador|embajador|judge|juez|jueza|journalist|periodista|reportero|"
    r"reporter|empresari[oa]|businessman|businesswoman|víctima|victim|vocero|spokesperson))\b"
)
_UP = r"[A-ZÁÉÍÓÚÑÜ][^\W\d_]+"
_NAME = rf"({_UP}(?:[ -]{_UP})+)"
_THIRD_PARTY = (
    re.compile(rf"{_ROLE}\s+{_NAME}"),  # Secretary Omar Synthetic
    re.compile(rf"{_ROLE}(?:\s+\w+){{1,6}},\s+{_NAME}"),  # secretario de Seguridad, Omar ...
    re.compile(rf"{_NAME},\s+(?:(?:el|la|the)\s+)?{_ROLE}"),  # Omar Synthetic, secretario
)


def _contains(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def in_text(value: str, body: str, aliases: Iterable[str] = ()) -> bool:
    """True if ``body`` has ``value`` as written, allowing a nickname inside a name."""
    wanted = normalize_alias(value)
    if not wanted:
        return False
    text = normalize_alias(body)
    if _contains(text, wanted) or _contains(normalize_alias(_QUOTED.sub(" ", body)), wanted):
        return True
    for alias in aliases:
        nick = normalize_alias(alias)
        if not nick or nick == wanted:
            continue
        if _contains(" ".join(f" {text} ".replace(f" {nick} ", " ").split()), wanted):
            return True
    return False


def supported_name(name: str, body: str, aliases: Sequence[str] = ()) -> str | None:
    """``name`` if the text has it, else the form the text does use, else None.

    An invented surname falls back to the text's own "given name + N"; failing that, to an
    alias the text has. A name the source does not contain is never stored.
    """
    if in_text(name, body, aliases):
        return name
    wanted = normalize_alias(name).split()
    found = [(m, normalize_alias(m.group())) for m in _WORD.finditer(body)]
    for size in range(len(wanted), 0, -1):
        target = wanted[:size]
        for i in range(len(found) - size):
            span = found[i : i + size + 1]
            if [w for _, w in span[:size]] != target or span[size][1] not in PLACEHOLDERS:
                continue
            start, end = span[0][0].start(), span[size][0].end()
            if end - start > len(" ".join(target)) + 8 or "\n" in body[start:end]:
                continue
            if end < len(body) and body[end] in "\"”»’'":  # noqa: RUF001
                end += 1
            return body[start:end]
    return next((a for a in aliases if in_text(a, body)), None)


def has_kinship(value: str, names: Iterable[str] = ()) -> bool:
    """Kinship words outside nicknames ("Tío Lako", "El Primo") and reported names."""
    text = _QUOTED.sub(" ", value)
    for name in sorted((n for n in names if n.strip()), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name.strip())}(?!\w)", " ", text, flags=re.IGNORECASE)
    return bool(_KIN.search(text))


def clean_title(value: str | None) -> str | None:
    """A title without its family part: "Primo y segundo al mando" -> "segundo al mando"."""
    if not value or not _KIN.search(value):
        return value
    kept = [p for p in _PART.split(value) if p and not _KIN.search(p)]
    return ", ".join(kept) or None


def names_third_party(quote: str, listed: Iterable[str]) -> bool:
    allowed = [set(normalize_alias(n).split()) for n in listed]
    for pattern in _THIRD_PARTY:
        for m in pattern.finditer(quote):
            named = set(normalize_alias(m.group(1)).split())
            if not any(len(named & person) >= min(2, len(named)) for person in allowed):
                return True
    return False


def safe_quote(quote: str | None, listed: Sequence[str]) -> str | None:
    """The quote, or None when it carries a family detail or a non-criminal third party."""
    if not quote or has_kinship(quote, listed) or names_third_party(quote, listed):
        return None
    return quote
