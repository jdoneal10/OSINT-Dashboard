"""Other articles' headlines inside an article's text (ADR 0004 amendment 2026-11-22).

Outlets put related-story links in the body: widgets (Quadratín's headline cards), a
labeled line ("Te puede interesar leer: ...", "SEE ALSO: ...") or a bare link path in a live
blog. Left in, a headline reads as part of the story: one became a false criminal charge
against a named person. They are removed before text is stored, so the filter, the model
and the reader never see them. The labels are a list: a new wording gets through until it
is added.
"""

from __future__ import annotations

import re

# Page blocks dropped before extraction: each headline card, not just the widget holding it,
# or the extractor takes the next widget's card instead. Exact class names: a broad match on
# "related" or "sidebar" would delete whole articles on some sites (DroneLife's body is in one).
WIDGET_XPATH = ["//*[contains(@class, 'q-side-notice')]"]

_LABEL = re.compile(
    r"^[^\w#]*(?:"
    r"(?:(?:te|le)\s+)?(?:puedes?|podr[ií]as?|prodr[ií]as?)\s+interesar(?:te|le)?(?:\s+leer)?"
    r"|(?:(?:te|le|les)\s+)?(?:sugerimos|recomendamos)(?:\s+leer)?"
    r"|(?:te|le)\s+invitamos\s+a\s+leer"
    r"|(?:puedes?|podr[ií]as?|debes?|deber[ií]as?|tienes?\s+que|no\s+dejes?\s+de)\s+leer(?:\s+tambi[eé]n)?"
    r"|(?:lee|leer|lea)(?:\s+(?:tambi[eé]n|m[aá]s))?"
    r"|tambi[eé]n\s+(?:lee|puedes\s+leer)"
    r"|nota\s+(?:relacionada|recomendada|sugerida)|relacionad[oa]s?|sugerid[oa]s?"
    r"|m[aá]s\s+(?:en\s+(?!concreto|detalle|general)\w+|de\s+la\s+lmp)"
    r"|sig(?:ue|a)\s+leyendo|ent[eé]rate"
    r"|see\s+also|read\s+(?:more|also|next)|related(?:\s+(?:stories|articles|posts))?"
    r")\s*[:>]\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_UPDATES = re.compile(r"^\W*read more updates\W*$", re.IGNORECASE)
# Live blogs (Infobae) leave each embedded story as a bare link path, its headline in the slug.
_PATH = re.compile(r"^\s*/\S+/\d{4}/\d{2}/\d{2}/\S+\s*$")
_BULLET = re.compile(r"^\s*[-•*]\s+\S")
_DATED = re.compile(r"^\W*[A-Z][a-z]+ \d{1,2}, \d{4}\s*[–—-]")  # noqa: RUF001


def strip_related(text: str) -> str:
    """``text`` without related-story lines and the link lists under them."""
    kept: list[str] = []
    listing: re.Pattern[str] | None = None
    for line in text.split("\n"):
        if listing and listing.match(line):
            continue
        listing = None
        if _PATH.match(line):
            continue
        if _UPDATES.match(line):
            listing = _DATED
            continue
        if m := _LABEL.match(line):
            if not m.group("rest").strip():
                listing = _BULLET  # a bare "Read more:" heads a list of links
            continue
        kept.append(line)
    return "\n".join(kept)
