"""Family details in model-written free text (hard rule 3; ADR 0013 amendment 2).

A family detail is kinship tied to an identifiable person: someone named, aliased or given as
"the leader" or "the target". Relatives described only by role ("mothers of the disappeared",
"a man walking with his wife") are ordinary reporting and stay.

Kinship is cut only where that cannot change who did what: directly before the name of a
listed person ("his cousin German N"), or as an aside after one ("X, brother of Y, was").
Otherwise the sentence is withheld. "The brother of X was sentenced" must never become "X was
sentenced". Word lists and patterns: they reduce the risk and do not prove its absence.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.reference.normalize import normalize_alias

WITHHELD = "[Withheld: family detail. See the cited source.]"

_KIN = (
    r"(?i:\b(?:half-)?(?:brothers?|sisters?|siblings?|twins?|cousins?|nephews?|nieces?|uncles?|"
    r"aunts?|fathers?|mothers?|parents|sons?|daughters?|wife|wives|husbands?|widow(?:er)?s?|"
    r"girlfriends?|boyfriends?|grand(?:son|daughter|father|mother|children)s?|"
    r"step(?:son|daughter|father|mother|brother|sister)s?|relatives)(?:-in-law)?\b)"
)
# Spanish appears in evidence quotes. Lower case only: "Los Hermanos X" is an organization.
_KIN_ES = (
    r"\b(?:prim[oa]s?|herman[oa]s?|hij[oa]s?|padre|madre|espos[oa]|sobrin[oa]s?|tí[oa]|"
    r"cuñad[oa]s?|yerno|nuera|suegr[oa]|novi[oa])\b"
)
_UP = r"[A-ZÁÉÍÓÚÑÜ][\w-]+"
_QUOTE = r"[\"“«][^\"”»\n]{1,30}[\"”»]"
_FIGURE = r"(?i:\b(?:alias|leader|capo|kingpin|boss|target|suspect|detainee|fugitive)\b)"
_FIGURE_ES = r"\b(?:alias|líder|capo|jefe|detenido|objetivo)\b"
# Words that make "relatives of ..." a role: victims, the missing, or just a place.
_ROLE_ONLY = r"(?i:in|on|at|near|from|victims?|missing|disappeared|killed|dead)\b"
_ROLE_ONLY_ES = r"(?:en|desaparecid\w+|víctimas?|muert\w+)\b"

_TIES = (
    # brother of CJNG leader X; nephew of the late capo X; cousin of the target
    re.compile(
        rf"{_KIN}\s+(?i:of)\s+(?:(?!{_ROLE_ONLY})[\w'’.-]+\s+){{0,5}}?"  # noqa: RUF001
        rf"(?:{_UP}\s+{_UP}|{_QUOTE}|{_FIGURE})"
    ),
    re.compile(rf"(?:\b{_UP}|{_QUOTE}|{_FIGURE})(?:'s|’s)\s+{_KIN}"),  # noqa: RUF001
    re.compile(rf"\b(?i:the)\s+(?:{_UP}\s+){{1,3}}(?i:brothers|sisters|siblings|cousins)\b"),
    re.compile(rf"{_KIN},?\s+(?:alias\b|{_UP}\s+{_UP})"),  # brothers X Y; brother, alias R2
    re.compile(r"(?i:\brelatives\s+(?:reported|described|identified)\s+as\b)"),
    re.compile(
        rf"{_KIN_ES}\s+(?:de|del)\s+(?:(?!{_ROLE_ONLY_ES})[\w.-]+\s+){{0,5}}?"
        rf"(?:{_UP}\s+{_UP}|{_QUOTE}|{_FIGURE_ES})"
    ),
    re.compile(rf"{_KIN_ES}\s+{_UP}\s+{_UP}"),
)
_POSSESSIVE = re.compile(rf"(?i:\b(?:his|her|their|whose))\s+{_KIN}|\bsu\s+{_KIN_ES}")
_PRONOUN_START = re.compile(r"^(?:He|She|His|Her|They|Their)\b")
_BEFORE_NAME = re.compile(
    rf"(?:\b(?i:his|her|their)\s+)?{_KIN}"
    rf"(?:\s+and\s+(?P<role>[a-z][\w-]*(?:\s+[a-z][\w-]*)?))?\s+(?P<name>{_UP})"
)
_ASIDE = re.compile(rf",\s+(?:(?:the|a)\s+)?{_KIN}\s+of\s+[^,]+,\s+(?=(?:was|were|is|has|had)\b)")
# Sentence ends, but not "U.S. Army", "No. 4", "Jr." or a middle initial.
_SENTENCE = re.compile(
    r"(?<=[.!?])(?<!U\.S\.)(?<!\bNo\.)(?<!\bJr\.)(?<!\b[A-Z]\.)\s+(?=[A-ZÁÉÍÓÚÑ\"“])"
)


def _has_name(text: str, listed: Sequence[str]) -> bool:
    padded = f" {normalize_alias(text)} "
    return any(f" {n} " in padded for v in listed if (n := normalize_alias(v)))


def has_family_detail(text: str, listed: Sequence[str] = ()) -> bool:
    """Kinship tied to an identifiable person. ``listed`` is the document's recorded persons."""
    for sentence in _SENTENCE.split(text):
        if any(p.search(sentence) for p in _TIES):
            return True
        names = _BEFORE_NAME.finditer(sentence) if listed else ()
        if any(_starts_listed(m.group("name"), listed) for m in names):
            return True
        if _POSSESSIVE.search(sentence) and (
            re.search(rf"{_FIGURE}\s+{_UP}\s+{_UP}", sentence)
            or _has_name(sentence, listed)
            or (listed and _PRONOUN_START.match(sentence))
        ):
            return True
    return False


def _starts_listed(word: str, listed: Sequence[str]) -> bool:
    return normalize_alias(word) in {normalize_alias(v).partition(" ")[0] for v in listed}


def _cut(sentence: str, listed: Sequence[str]) -> str:
    def before_name(m: re.Match[str]) -> str:
        if not _starts_listed(m.group("name"), listed):
            return m.group()
        role = f"{m.group('role')} " if m.group("role") else ""
        return f"{role}{m.group('name')}"

    out = _BEFORE_NAME.sub(before_name, sentence)
    if (m := _ASIDE.search(out)) and _has_name(out[: m.start()], listed):
        out = f"{out[: m.start()]} {out[m.end() :]}"
    return out


def clean_text(text: str, listed: Sequence[str] = ()) -> str:
    """``text`` without family details; ``WITHHELD`` if no sentence can be kept."""
    if not has_family_detail(text, listed):
        return text
    kept = []
    for sentence in _SENTENCE.split(text):
        if not has_family_detail(sentence, listed):
            kept.append(sentence)
        elif not has_family_detail(cut := _cut(sentence, listed), listed):
            kept.append(cut)
    return " ".join(kept) or WITHHELD


def clean_quote(quote: str | None, listed: Sequence[str] = ()) -> str | None:
    """A quote is never edited: it is kept whole or withheld."""
    return None if quote and has_family_detail(quote, listed) else quote
