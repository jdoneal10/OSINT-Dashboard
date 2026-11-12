"""Local relevance filter (Ollama on 127.0.0.1). No data leaves the machine; no API spend.

Scores each ``pipeline_status='new'`` document for relevance to the intelligence requirements
(TCO violence, territory, trafficking, seizures, precursors, designations, border security
in Mexico, Central America and the U.S. border). Documents at or above
``OSINT_RELEVANCE_THRESHOLD`` become ``relevant``; the rest ``filtered_out``.

Tuned for **recall**: a borderline article costs a fraction of a cent at Haiku; a missed one is
lost. The model and threshold are chosen on the owner's labeled set (Step 6).

Documents ingested before the filter existed, or whose text is empty, are handled too:
empty -> ``skipped``.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, LLMQuarantine
from app.db.session import session_factory

log = logging.getLogger(__name__)

PROMPT_VERSION = "filter-v1"
MAX_CHARS = 6000  # title + lead paragraphs are enough to judge relevance

SYSTEM = """You screen news articles and official press releases for an analyst who tracks \
transnational criminal organizations (drug cartels, gangs) in Mexico, Central America and the \
U.S. Southwest border.

RELEVANT (score high): cartel or gang violence; homicides, kidnappings, extortion, \
disappearances or clandestine graves linked to organized crime; clashes between armed groups \
or with security forces; territorial disputes; drug, weapon, cash or precursor-chemical \
seizures; trafficking routes, smuggling, labs; arrests or prosecutions of criminal \
organizations; sanctions, terrorist designations or indictments of cartels; border \
enforcement statistics.

NOT RELEVANT (score low): ordinary politics, economy, sports, entertainment, weather, \
traffic accidents, health, or crime with no organized-crime link; anything outside \
Mexico/Central America/the U.S. border unless it involves those organizations.

When unsure, score toward relevant. Reply with JSON only: "relevance" from 0 to 1 and a \
"reason" of at most 25 words."""


class FilterOutput(BaseModel):
    relevance: float = Field(ge=0, le=1)
    reason: str  # informational only; long reasons are truncated, never rejected

    @field_validator("reason")
    @classmethod
    def _short(cls, v: str) -> str:
        return v[:300]


FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 300},
    },
    "required": ["relevance", "reason"],
}


class OllamaUnavailableError(RuntimeError):
    """Ollama is not running or the model is not pulled."""


def document_text(doc: Document) -> str:
    parts = [doc.title or "", doc.summary or "", doc.original_text or ""]
    return "\n\n".join(p for p in parts if p).strip()[:MAX_CHARS]


class LocalFilter:
    def __init__(self, model: str | None = None, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.relevance_model
        self.url = settings.ollama_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    def score(self, text: str) -> FilterOutput:
        try:
            resp = self._client.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": FORMAT_SCHEMA,
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"ARTICLE:\n{text}"},
                    ],
                },
            )
        except httpx.TransportError as exc:
            raise OllamaUnavailableError(f"Ollama not reachable at {self.url}: {exc}") from exc
        if resp.status_code == 404:
            raise OllamaUnavailableError(
                f"model {self.model!r} not found; run `ollama pull {self.model}`"
            )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return FilterOutput.model_validate(json.loads(content))


def run_filter(limit: int = 500, local: LocalFilter | None = None) -> dict[str, int]:
    """Score up to ``limit`` new documents. Returns counts by outcome."""
    local = local or LocalFilter()
    threshold = Decimal(str(get_settings().relevance_threshold))
    counts = {"relevant": 0, "filtered_out": 0, "skipped": 0, "error": 0}
    with session_factory()() as session:
        ids = list(
            session.scalars(
                select(Document.id)
                .where(Document.pipeline_status == "new", Document.duplicate_of_id.is_(None))
                .order_by(Document.id)
                .limit(limit)
            )
        )
    for doc_id in ids:
        with session_factory()() as session, session.begin():
            doc = session.get_one(Document, doc_id)
            text = document_text(doc)
            if not text:
                doc.pipeline_status = "skipped"
                counts["skipped"] += 1
                continue
            try:
                out = local.score(text)
            except (ValidationError, json.JSONDecodeError, httpx.HTTPStatusError) as exc:
                session.add(
                    LLMQuarantine(
                        stage="filter",
                        document_id=doc.id,
                        model=local.model,
                        prompt_version=PROMPT_VERSION,
                        reason="validation",
                        error=str(exc)[:4000],
                    )
                )
                doc.pipeline_status = "quarantined"
                counts["error"] += 1
                continue
            score = Decimal(str(round(out.relevance, 3)))
            doc.relevance_score = score
            doc.relevance_model = f"{local.model}/{PROMPT_VERSION}"
            doc.pipeline_status = "relevant" if score >= threshold else "filtered_out"
            counts[doc.pipeline_status] += 1
    log.info("local filter (%s): %s", local.model, counts)
    return counts
