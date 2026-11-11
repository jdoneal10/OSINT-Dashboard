"""Core schema (PLAN.md §6).

Conventions:
- Enumerated values are ``String`` + ``CHECK`` constraints, not PostgreSQL ENUMs, so adding
  a value is a one-line migration.
- Geography is ``geography(..., 4326)`` with GiST indexes.
- Every source-derived table uses :class:`ProvenanceMixin`; derived records link back to the
  documents they came from through association tables.
- Named individuals never get their own table (CLAUDE.md hard rule 3). They appear only as
  attributes of public legal-action records (``designations.listed_parties``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography, WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    LLMDerivedMixin,
    ProvenanceMixin,
    TimestampMixin,
    provenance_table_args,
)


# Factories, not shared instances: GeoAlchemy2 mutates a type's ``nullable`` when it is
# attached to a column, so one shared instance leaks NOT NULL across tables.
# GiST indexes are declared explicitly via ``_gist`` (spatial_index=False here).
def POINT() -> Geography:  # noqa: N802
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def MULTIPOLYGON() -> Geography:  # noqa: N802
    return Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False)


# Citation list stored with reference rows: [{"title", "publisher", "url", "accessed"}].
Citations = list[dict[str, Any]]


def _check_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name)


def _gist(table: str, column: str) -> Index:
    return Index(f"ix_{table}_{column}_gist", column, postgresql_using="gist")


# --------------------------------------------------------------------------- sources


SOURCE_TYPES = ("api", "dataset", "rss", "web", "reference")


class Source(TimestampMixin, Base):
    """A data source and its Admiralty reliability grade (A..F) and terms of use."""

    __tablename__ = "sources"
    __table_args__ = (
        _check_in("source_type", SOURCE_TYPES, "source_type"),
        CheckConstraint("reliability IN ('A','B','C','D','E','F')", "reliability"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    source_type: Mapped[str] = mapped_column(String(16))
    reliability: Mapped[str] = mapped_column(String(1), default="F")
    homepage_url: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    license_notes: Mapped[str | None] = mapped_column(Text)
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------- documents


class Document(ProvenanceMixin, LLMDerivedMixin, TimestampMixin, Base):
    """A retrieved article, report or release. LLM columns describe the translation step."""

    __tablename__ = "documents"
    __table_args__ = (*provenance_table_args("documents"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None]
    language: Mapped[str | None] = mapped_column(String(8))
    original_text: Mapped[str | None] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)


# --------------------------------------------------------------------------- actors


ACTOR_TYPES = ("tco", "faction", "armed_group", "state", "civilian", "other")


class Actor(TimestampMixin, Base):
    """Canonical organization record. Organizations only — no private individuals."""

    __tablename__ = "actors"
    __table_args__ = (_check_in("actor_type", ACTOR_TYPES, "actor_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    canonical_name: Mapped[str] = mapped_column(String(256), unique=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("actors.id"))
    country_iso3: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[Citations] = mapped_column(default=list)


class ActorAlias(TimestampMixin, Base):
    __tablename__ = "actor_aliases"
    __table_args__ = (UniqueConstraint("actor_id", "alias_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("actors.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(String(256))
    alias_normalized: Mapped[str] = mapped_column(String(256), index=True)
    language: Mapped[str | None] = mapped_column(String(8))
    sources: Mapped[Citations] = mapped_column(default=list)


# --------------------------------------------------------------------------- events


class Event(ProvenanceMixin, LLMDerivedMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        *provenance_table_args("events"),
        CheckConstraint("fatalities IS NULL OR fatalities >= 0", "fatalities"),
        _gist("events", "geom"),
        Index("ix_events_event_date", "event_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[dt.date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(64))
    sub_event_type: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    fatalities: Mapped[int | None] = mapped_column(Integer)
    geom: Mapped[WKBElement | None] = mapped_column(POINT())
    country_iso3: Mapped[str | None] = mapped_column(String(3))
    admin1_code: Mapped[str | None] = mapped_column(String(16), index=True)
    admin2_code: Mapped[str | None] = mapped_column(String(16))
    # 1 = exact point, 2 = near/municipality, 3 = admin1 or coarser (ACLED-style scale).
    geo_precision: Mapped[int | None] = mapped_column(SmallInteger)


ACTOR_ROLES = ("perpetrator", "target", "other")

actor_events = Table(
    "actor_events",
    Base.metadata,
    Column("actor_id", ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True),
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(16), primary_key=True),
    _check_in("role", ACTOR_ROLES, "role"),
)

event_documents = Table(
    "event_documents",
    Base.metadata,
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------- corridor graph


NODE_TYPES = (
    "poe",
    "usbp_sector",
    "seaport",
    "airport",
    "lab_region",
    "transit_hub",
    "crossing",
)
EDGE_MODES = ("land", "maritime", "air", "rail")


class Node(TimestampMixin, Base):
    """Corridor-graph node. ``point`` is the representative point; ``area`` is optional.

    Both may be NULL for nodes with no public geometry (e.g. USBP sectors, ADR 0002).
    """

    __tablename__ = "nodes"
    __table_args__ = (
        _check_in("node_type", NODE_TYPES, "node_type"),
        _gist("nodes", "point"),
        _gist("nodes", "area"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    node_type: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str | None] = mapped_column(String(32))
    country_iso3: Mapped[str | None] = mapped_column(String(3))
    admin1_code: Mapped[str | None] = mapped_column(String(16))
    point: Mapped[WKBElement | None] = mapped_column(POINT())
    area: Mapped[WKBElement | None] = mapped_column(MULTIPOLYGON())
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    sources: Mapped[Citations] = mapped_column(default=list)


class Edge(TimestampMixin, Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint("from_node_id", "to_node_id", "mode"),
        _check_in("mode", EDGE_MODES, "mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    to_node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[Citations] = mapped_column(default=list)


class ReferenceArea(TimestampMixin, Base):
    """Area-of-interest polygons (admin1 units per phase)."""

    __tablename__ = "reference_areas"
    __table_args__ = (_gist("reference_areas", "geom"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    area_type: Mapped[str] = mapped_column(String(32))
    country_iso3: Mapped[str] = mapped_column(String(3))
    admin1_code: Mapped[str | None] = mapped_column(String(16))
    phase: Mapped[int] = mapped_column(SmallInteger)
    geom: Mapped[WKBElement] = mapped_column(MULTIPOLYGON())
    sources: Mapped[Citations] = mapped_column(default=list)


# --------------------------------------------------------------------------- precursors & trade


CHEMICAL_ROLES = ("precursor", "pre_precursor", "essential")


class ChemicalWatchlist(TimestampMixin, Base):
    __tablename__ = "chemical_watchlist"
    __table_args__ = (_check_in("role", CHEMICAL_ROLES, "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True)
    aliases: Mapped[list[str]] = mapped_column(default=list)
    cas_number: Mapped[str | None] = mapped_column(String(32))
    hs_code: Mapped[str | None] = mapped_column(String(16), index=True)
    control_status: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    sources: Mapped[Citations] = mapped_column(default=list)


class Seizure(ProvenanceMixin, LLMDerivedMixin, TimestampMixin, Base):
    __tablename__ = "seizures"
    __table_args__ = (
        *provenance_table_args("seizures"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", "quantity"),
        _gist("seizures", "geom"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seizure_date: Mapped[dt.date] = mapped_column(Date, index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"))
    geom: Mapped[WKBElement | None] = mapped_column(POINT())
    substance: Mapped[str] = mapped_column(String(256))
    chemical_id: Mapped[int | None] = mapped_column(ForeignKey("chemical_watchlist.id"))
    chemical_class: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(16))
    seizing_agency: Mapped[str | None] = mapped_column(String(256))
    country_iso3: Mapped[str | None] = mapped_column(String(3))
    admin1_code: Mapped[str | None] = mapped_column(String(16))


seizure_documents = Table(
    "seizure_documents",
    Base.metadata,
    Column("seizure_id", ForeignKey("seizures.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
)


class TradeFlow(ProvenanceMixin, TimestampMixin, Base):
    """Country-level trade aggregates (e.g. Comtrade). Shows trends, not importers."""

    __tablename__ = "trade_flows"
    __table_args__ = (
        *provenance_table_args("trade_flows"),
        CheckConstraint("flow IN ('import','export')", "flow"),
        Index("ix_trade_flows_hs_period", "hs_code", "period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_iso3: Mapped[str] = mapped_column(String(3))
    partner_iso3: Mapped[str] = mapped_column(String(3))
    hs_code: Mapped[str] = mapped_column(String(16))
    period: Mapped[dt.date] = mapped_column(Date)  # first day of the month
    flow: Mapped[str] = mapped_column(String(8))
    net_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    trade_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))


# --------------------------------------------------------------------------- border metrics


class BorderMetric(TimestampMixin, Base):
    """CBP figures by AOR and month. Revised until FY close, so every pull is a new
    ``snapshot_date`` row and history is never overwritten."""

    __tablename__ = "border_metrics"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "metric",
            "aor_node_id",
            "month",
            "dimension_key",
            "snapshot_date",
            name="uq_border_metrics_snapshot",
        ),
        Index("ix_border_metrics_month", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[dt.datetime]
    snapshot_date: Mapped[dt.date] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(String(64))
    aor_node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"))
    aor_label: Mapped[str] = mapped_column(String(128))
    fiscal_year: Mapped[int] = mapped_column(SmallInteger)
    month: Mapped[dt.date] = mapped_column(Date)
    # Breakdown such as demographic or drug type; dimension_key is its canonical string.
    dimensions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dimension_key: Mapped[str] = mapped_column(String(512), default="")
    value: Mapped[Decimal] = mapped_column(Numeric(20, 3))
    unit: Mapped[str | None] = mapped_column(String(16))


# --------------------------------------------------------------------------- legal actions


DESIGNATION_TYPES = ("fto", "sdgt", "sdn", "indictment", "other")


class Designation(ProvenanceMixin, TimestampMixin, Base):
    """FTO / OFAC / DOJ actions. ``listed_parties`` holds names exactly as they appear in
    the public record; they are attributes of the record, never standalone entities."""

    __tablename__ = "designations"
    __table_args__ = (
        *provenance_table_args("designations"),
        _check_in("designation_type", DESIGNATION_TYPES, "designation_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    designation_type: Mapped[str] = mapped_column(String(16))
    program: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    action_date: Mapped[dt.date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(Text)
    listed_parties: Mapped[list[dict[str, Any]]] = mapped_column(default=list)


designation_actors = Table(
    "designation_actors",
    Base.metadata,
    Column("designation_id", ForeignKey("designations.id", ondelete="CASCADE"), primary_key=True),
    Column("actor_id", ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True),
)


# --------------------------------------------------------------------------- analysis & ops


ALERT_STATUSES = ("new", "acknowledged", "dismissed")


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (_check_in("status", ALERT_STATUSES, "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[str] = mapped_column(String(64), index=True)
    triggered_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="new")
    severity: Mapped[int] = mapped_column(SmallInteger, default=1)
    summary: Mapped[str] = mapped_column(Text)
    linked_records: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Annotation(TimestampMixin, Base):
    """Analyst notes. Never sent to any external API (CLAUDE.md LLM pipeline rules)."""

    __tablename__ = "annotations"
    __table_args__ = (Index("ix_annotations_target", "target_table", "target_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_table: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[int] = mapped_column(BigInteger)
    body: Mapped[str] = mapped_column(Text)


class LLMUsage(Base):
    """One row per LLM call; drives the monthly budget cap."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    called_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    batch: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    status: Mapped[str] = mapped_column(String(16), default="ok")
    request_id: Mapped[str | None] = mapped_column(String(128))


INGEST_STATUSES = ("running", "ok", "error")


class IngestRun(Base):
    """Audit log for every scheduled or manual job run."""

    __tablename__ = "ingest_runs"
    __table_args__ = (_check_in("status", INGEST_STATUSES, "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    started_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[dt.datetime | None]
    status: Mapped[str] = mapped_column(String(16), default="running")
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_deleted: Mapped[int] = mapped_column(Integer, default=0)
    raw_path: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
