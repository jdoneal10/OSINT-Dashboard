"""Registry of unstructured sources (``data/reference/feeds.yaml``, ADR 0004).

Each feed becomes a ``sources`` row (slug, Admiralty reliability, terms note) so documents
carry normal provenance. Only ``status: active`` feeds are ingested.
"""

from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Source
from app.reference.schemas import Cited


class Feed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    domain: str
    country: str = Field(pattern=r"^[A-Z]{3}$")
    language: Literal["en", "es"]
    discovery: Literal["rss", "listing", "gdelt"]
    url: HttpUrl | None = None
    link_pattern: str | None = None
    text: Literal["full", "summary"]
    reliability: Literal["A", "B", "C", "D", "E", "F"]
    status: Literal["active", "pending"]
    terms_note: str
    sources: Cited

    @field_validator("sources")
    @classmethod
    def _cited(cls, v: Cited) -> Cited:
        if not v:
            raise ValueError("at least one citation is required")
        return v

    @model_validator(mode="after")
    def _discovery_fields(self) -> Feed:
        if self.discovery in ("rss", "listing") and self.url is None:
            raise ValueError(f"{self.slug}: {self.discovery} discovery needs a url")
        if self.discovery == "listing" and self.status == "active" and not self.link_pattern:
            raise ValueError(f"{self.slug}: listing discovery needs a link_pattern")
        if self.link_pattern:
            re.compile(self.link_pattern)
        return self


class FeedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    checked: dt.date
    feeds: list[Feed]


def feeds_path() -> Path:
    return get_settings().reference_dir / "feeds.yaml"


@lru_cache
def _load(path: Path, mtime: float) -> FeedFile:  # mtime busts the cache when the file changes
    return FeedFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_feeds(path: Path | None = None) -> list[Feed]:
    path = path or feeds_path()
    return _load(path, path.stat().st_mtime).feeds


def active(discovery: str | None = None, path: Path | None = None) -> list[Feed]:
    return [
        f
        for f in load_feeds(path)
        if f.status == "active" and (discovery is None or f.discovery == discovery)
    ]


def sync_sources(session: Session, feeds: list[Feed] | None = None) -> int:
    """Upsert one ``sources`` row per feed (idempotent)."""
    feeds = feeds if feeds is not None else load_feeds()
    for feed in feeds:
        values = {
            "slug": feed.slug,
            "name": feed.name,
            "source_type": "rss" if feed.discovery == "rss" else "web",
            "reliability": feed.reliability,
            "homepage_url": f"https://{feed.domain}",
            "terms_url": str(feed.sources[0].url),
            "license_notes": feed.terms_note,
            "redistribution_allowed": False,
        }
        stmt = insert(Source).values(**values)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Source.slug],
                set_={k: stmt.excluded[k] for k in values if k != "slug"}
                | {"updated_at": func.now()},
            )
        )
    return len(feeds)
