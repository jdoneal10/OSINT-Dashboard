"""Shared helpers for the ACLED note passes (grid, ADR 0014; UxS, ADR 0009 amendment 1).

Each pass sends the notes of matching ACLED events to Haiku, one event per request, checks the
model's quote against the notes, and keeps the hash of the notes it classified so an ACLED
edit queues the event again.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import ColumnElement, func

from app.db.models import Event

ACTOR_KEYS = ("actor1", "assoc_actor_1", "actor2", "assoc_actor_2")


def notes_hash(notes: str) -> str:
    return hashlib.sha256(notes.encode("utf-8")).hexdigest()


def current_notes_hash() -> ColumnElement[str]:
    """SQL expression: the hash of an event's current notes (compare with ``notes_hash``)."""
    return func.encode(func.sha256(func.convert_to(Event.description, "UTF8")), "hex")


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def actors(ev: Event) -> str:
    attrs = ev.attributes or {}
    return "; ".join(str(attrs[k]) for k in ACTOR_KEYS if attrs.get(k))


# A quote may join fragments with an ellipsis or ";", carry the prompt's "Actors:"/"Note:"
# labels, or end with a stray bracket; each remaining fragment must still be verbatim.
_QUOTE_SPLIT = re.compile(r"\.\.\.|…|;|\bactors:|\bnote:", re.IGNORECASE)


def quote_found(quote: str, ev: Event) -> bool:
    """True if every fragment of ``quote`` appears in the event's actors or notes (ACLED's text,
    which is all the model was shown besides the header)."""
    source = _normalized(f"{actors(ev)} {ev.description or ''}")
    fragments = [_normalized(f).strip(" .,;:'\"{}[]") for f in _QUOTE_SPLIT.split(quote)]
    fragments = [f for f in fragments if len(f) >= 3]
    return bool(fragments) and all(f in source for f in fragments)


def build_user(ev: Event) -> str:
    who = actors(ev)
    place = ", ".join(p for p in (ev.admin2_name, ev.admin1_name) if p)
    return (
        f"ACLED event {ev.source_key} ({ev.event_date.isoformat()}; {place or 'place unknown'}; "
        f"{ev.event_type} / {ev.sub_event_type or '-'})\n"
        f"Actors: {who or 'not given'}\n"
        f"Note: {ev.description or ''}"
    )
