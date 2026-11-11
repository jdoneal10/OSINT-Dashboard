"""Validation schemas for committed reference data in ``data/reference/``.

CLAUDE.md hard rule 2: every reference entry carries a public source citation, so
``sources`` is required and non-empty on every entry. Loading fails on any violation.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.db.models import ACTOR_TYPES, NODE_TYPES


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3)
    publisher: str = Field(min_length=2)
    url: HttpUrl
    accessed: dt.date
    note: str | None = None


Cited = list[Citation]


def _nonempty(v: Cited) -> Cited:
    if not v:
        raise ValueError("at least one public source citation is required")
    return v


# --------------------------------------------------------------------------- GeoJSON


class Geometry(BaseModel):
    type: Literal["Point", "Polygon", "MultiPolygon"]
    coordinates: list[Any]


class AreaProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    area_type: str
    country_iso3: str = Field(pattern=r"^[A-Z]{3}$")
    admin1_code: str | None = None
    phase: int = Field(ge=1, le=5)
    sources: Cited

    _cited = field_validator("sources")(_nonempty)


class AreaFeature(BaseModel):
    type: Literal["Feature"]
    geometry: Geometry
    properties: AreaProperties

    @field_validator("geometry")
    @classmethod
    def _polygonal(cls, g: Geometry) -> Geometry:
        if g.type == "Point":
            raise ValueError("reference areas must be Polygon or MultiPolygon")
        return g


class NodeProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    node_type: str
    code: str | None = None
    country_iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    admin1_code: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    sources: Cited

    _cited = field_validator("sources")(_nonempty)

    @field_validator("node_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in NODE_TYPES:
            raise ValueError(f"node_type must be one of {NODE_TYPES}")
        return v


class NodeFeature(BaseModel):
    type: Literal["Feature"]
    geometry: Geometry | None  # null when no public geometry exists (ADR 0002)
    properties: NodeProperties


class AreaCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[AreaFeature]


class NodeCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[NodeFeature]


# --------------------------------------------------------------------------- actors


class AliasEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1)
    language: str | None = None


class ActorEntry(BaseModel):
    """An organization. Hard rule 3: no private individuals as actors."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    canonical_name: str
    actor_type: str
    country_iso3: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    parent: str | None = None
    description: str | None = None
    aliases: list[AliasEntry | str] = Field(default_factory=list)
    sources: Cited

    _cited = field_validator("sources")(_nonempty)

    @field_validator("actor_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in ACTOR_TYPES:
            raise ValueError(f"actor_type must be one of {ACTOR_TYPES}")
        return v

    def alias_entries(self) -> list[AliasEntry]:
        return [a if isinstance(a, AliasEntry) else AliasEntry(alias=a) for a in self.aliases]


class ActorFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    actors: list[ActorEntry]
