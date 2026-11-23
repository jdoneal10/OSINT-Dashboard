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
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
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


def _check_array_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} <@ ARRAY[{quoted}]::varchar[]", name)


def _check_null_or_in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IS NULL OR {column} IN ({quoted})", name)


def _gist(table: str, column: str) -> Index:
    return Index(f"ix_{table}_{column}_gist", column, postgresql_using="gist")


# --------------------------------------------------------------------------- sources


SOURCE_TYPES = ("api", "dataset", "rss", "web", "reference", "email")


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


PIPELINE_STATUSES = (
    "new",
    "filtered_out",
    "relevant",
    "batched",  # submitted to the Message Batches API; awaiting results
    "extracted",
    "quarantined",
    "skipped",
)


class Document(ProvenanceMixin, LLMDerivedMixin, TimestampMixin, Base):
    """A retrieved article, report or release. LLM columns describe the translation step.

    ``pipeline_status`` moves new -> filtered_out | relevant [-> batched] -> extracted |
    quarantined
    (``skipped`` = not processable, e.g. empty text). ACLED never appears here (ADR 0003).
    """

    __tablename__ = "documents"
    __table_args__ = (
        *provenance_table_args("documents"),
        _check_in("pipeline_status", PIPELINE_STATUSES, "pipeline_status"),
        Index("ix_documents_pipeline_status", "pipeline_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None]
    language: Mapped[str | None] = mapped_column(String(8))
    original_text: Mapped[str | None] = mapped_column(Text)
    translated_text: Mapped[str | None] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, index=True)
    summary: Mapped[str | None] = mapped_column(Text)  # feed teaser or LLM English summary
    text_policy: Mapped[str] = mapped_column(String(16), default="full")  # full | summary
    pipeline_status: Mapped[str] = mapped_column(String(16), default="new")
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    relevance_model: Mapped[str | None] = mapped_column(String(64))
    # Near-duplicate of another document (syndication / reposts); counted once for corroboration.
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))


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


# Priority threat categories for news-derived events (ADR 0007). Threat activity only:
# never friendly-force positions, numbers, equipment or tactics (CLAUDE.md hard rule 4).
BORDER_THREATS = (
    "human_smuggling",  # smuggling loads, stash houses, smuggling deaths, organizations
    "uas_incursion",  # criminal drones crossing or operating at the border
    "laser_strike",  # lasers aimed at aircraft or personnel at the border
    "gunfire",  # shots fired at or across the border
    "assault_on_personnel",  # attacks on border officers or soldiers
    "tunnel",  # cross-border tunnels
    "other_border_threat",
)


# Unmanned systems and electricity theft (owner framework, docs/framework/
# uxs-and-electricity-theft.md; ADR 0009). Categories are owner judgment; values on a record
# are what its source reports.
UXS_PLATFORMS = (
    "suas_multirotor", "fpv", "fixed_wing", "heavy_lift_or_hybrid", "ugv", "usv", "unknown",
)  # fmt: skip
UXS_MISSIONS = (
    "surveillance", "route_security", "overwatch", "attack", "logistics",
    "coercion_or_propaganda", "surveillance_of_security_forces", "monitoring_economic_activity",
)  # fmt: skip
UXS_PAYLOADS = (
    "explosive_or_grenade", "ied", "camera_or_thermal", "release_mechanism", "supply",
    "loudspeaker_or_light", "none_reported",
)  # fmt: skip
UXS_ACTIVITIES = (
    "employment", "recovery_or_seizure", "procurement_or_import", "assembly_or_modification",
    "training", "prosecution",
)  # fmt: skip
ENERGY_METHODS = (
    "meter_bypass", "illegal_line_connection", "transformer_or_feeder_tampering",
    "insider_facilitation", "unknown",
)  # fmt: skip
ENERGY_POWERED = (
    "crypto_mining", "cultivation", "drug_lab", "warehouse_or_storage", "refrigeration",
    "communications", "residential_compound", "other",
)  # fmt: skip
ENERGY_FACILITATORS = (
    "utility_employee", "contractor", "electrician", "official", "property_manager",
    "none_reported",
)  # fmt: skip


class Event(ProvenanceMixin, LLMDerivedMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        *provenance_table_args("events"),
        CheckConstraint("fatalities IS NULL OR fatalities >= 0", "fatalities"),
        CheckConstraint(
            "border_threat IS NULL OR border_threat IN "
            f"({', '.join(repr(t) for t in BORDER_THREATS)})",
            "border_threat",
        ),
        _gist("events", "geom"),
        Index("ix_events_event_date", "event_date"),
        _check_null_or_in("uxs_platform", UXS_PLATFORMS, "uxs_platform"),
        _check_null_or_in("uxs_activity", UXS_ACTIVITIES, "uxs_activity"),
        _check_array_in("uxs_missions", UXS_MISSIONS, "uxs_missions"),
        _check_array_in("uxs_payloads", UXS_PAYLOADS, "uxs_payloads"),
        CheckConstraint("(uxs_activity IS NULL) = (uxs_platform IS NULL)", "uxs_complete"),
        _check_null_or_in("energy_method", ENERGY_METHODS, "energy_method"),
        _check_array_in("energy_powered", ENERGY_POWERED, "energy_powered"),
        _check_null_or_in("energy_facilitator", ENERGY_FACILITATORS, "energy_facilitator"),
        CheckConstraint(
            "(energy_method IS NULL) = (energy_facilitator IS NULL)", "energy_theft_complete"
        ),
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
    # 1 = exact day, 2 = within a week, 3 = a month or less precise, including an unknown date
    # or one taken from publication (ACLED-style scale).
    time_precision: Mapped[int | None] = mapped_column(SmallInteger)
    admin1_name: Mapped[str | None] = mapped_column(String(128))
    admin2_name: Mapped[str | None] = mapped_column(String(128))
    location_name: Mapped[str | None] = mapped_column(String(256))
    # Source-specific fields kept verbatim (e.g. ACLED actor strings, inter codes, tags) so
    # derived steps such as actor normalization can be re-run without re-fetching.
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("event_clusters.id"), index=True)
    # False for news-derived records placed outside the current AOI (e.g. Bolivia): kept for
    # context, hidden from feeds and the map by default (ADR 0004).
    in_aoi: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Priority border-threat category (news-derived events; ADR 0007), else NULL.
    border_threat: Mapped[str | None] = mapped_column(String(32), index=True)
    # Unmanned systems (extract-v7): set when the event involves criminal UxS; activity says
    # what happened (employment, seizure, procurement, assembly, training, prosecution).
    uxs_activity: Mapped[str | None] = mapped_column(String(32), index=True)
    uxs_platform: Mapped[str | None] = mapped_column(String(32))
    uxs_missions: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), default=list, server_default="{}"
    )
    uxs_payloads: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), default=list, server_default="{}"
    )
    # Electricity theft (extract-v7): reported cases only, never inferred sites (ADR 0009 §4).
    energy_method: Mapped[str | None] = mapped_column(String(40), index=True)
    energy_powered: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=list, server_default="{}"
    )
    energy_facilitator: Mapped[str | None] = mapped_column(String(32))
    energy_scale: Mapped[str | None] = mapped_column(String(200))  # as reported, never estimated


# actor1..assoc_actor2 mirror ACLED's dyad exactly (no perpetrator/target semantics);
# perpetrator/target are reserved for LLM-derived roles from Phase 2.
ACTOR_ROLES = (
    "perpetrator",
    "target",
    "other",
    "actor1",
    "actor2",
    "assoc_actor1",
    "assoc_actor2",
)

actor_events = Table(
    "actor_events",
    Base.metadata,
    Column("actor_id", ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True),
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(16), primary_key=True),
    _check_in("role", ACTOR_ROLES, "role"),
    # The PK leads with actor_id; event -> actors lookups (map, API) need their own index.
    Index("ix_actor_events_event_id", "event_id"),
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
    "ofo_field_office",
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
    admin2_code: Mapped[str | None] = mapped_column(String(16), index=True)  # INEGI cvegeo
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
    in_aoi: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Owner's priority judgment (docs/framework/seizure-priority.md): small drug amounts and
    # contraband goods. A correct record, hidden from the feed by default like out-of-AOI.
    low_priority: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


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


# --------------------------------------------------------------------------- persons (ADR 0013)
# Hard rule 3 / ADR 0008: only people an open source links to criminal activity. Every
# attribute and link is a cited claim: one row per source record, with its date and Admiralty
# grade, shown as reported. A person with no remaining citation is deleted (no uncited
# person exists). Contact and personal-life details have no column, by design.

PERSON_ATTRIBUTES = ("role", "alias", "nationality", "status", "title")
PERSON_STATUSES = (
    "arrested", "charged", "convicted", "sentenced", "extradited", "killed", "fugitive",
    "released", "designated",
)  # fmt: skip
PERSON_ORG_ROLES = (
    "leader", "member", "facilitator", "operator_or_technician", "supplier",
    "front_business_owner", "financier", "complicit_official", "associate",
)  # fmt: skip
PERSON_EVENT_ROLES = (
    "perpetrator", "directed", "arrested", "charged", "convicted_or_sentenced", "extradited",
    "killed", "escaped",
)  # fmt: skip


class Person(TimestampMixin, Base):
    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256))  # as the first source wrote it
    # Normalized full name used to match reports of the same person; NULL when the name is too
    # thin to match safely (under three name words, a nickname, or a placeholder such as "N").
    name_key: Mapped[str | None] = mapped_column(String(256), index=True)
    # Reported U.S. citizen, resident or U.S.-located: hidden from person views and search by
    # default (hard rule 3; the owner's EO 12333 boundary). Set by any citing record.
    us_person: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    disputed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    dispute_note: Mapped[str | None] = mapped_column(Text)


class PersonCitationMixin:
    """The source record behind one person claim (hard rule 3: cited, dated, graded)."""

    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    designation_id: Mapped[int | None] = mapped_column(
        ForeignKey("designations.id", ondelete="CASCADE"), index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    reported_on: Mapped[dt.date] = mapped_column(Date)
    reliability: Mapped[str] = mapped_column(String(1))
    credibility: Mapped[int] = mapped_column(SmallInteger)
    evidence: Mapped[str | None] = mapped_column(String(300))
    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))


def _citation_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("document_id IS NOT NULL OR designation_id IS NOT NULL", "cited"),
        _check_in("reliability", ("A", "B", "C", "D", "E", "F"), "reliability"),
        CheckConstraint("credibility BETWEEN 1 AND 6", "credibility"),
    )


class PersonAttribute(PersonCitationMixin, TimestampMixin, Base):
    __tablename__ = "person_attributes"
    __table_args__ = (
        *_citation_checks(),
        _check_in("attribute", PERSON_ATTRIBUTES, "attribute"),
        UniqueConstraint(
            "person_id", "attribute", "value", "document_id", "designation_id",
            postgresql_nulls_not_distinct=True,
        ),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(primary_key=True)
    attribute: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(256))


class PersonOrganization(PersonCitationMixin, TimestampMixin, Base):
    __tablename__ = "person_organizations"
    __table_args__ = (
        *_citation_checks(),
        _check_in("role", PERSON_ORG_ROLES, "role"),
        UniqueConstraint(
            "person_id", "actor_id", "role", "document_id", "designation_id",
            postgresql_nulls_not_distinct=True,
        ),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("actors.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))


class PersonEvent(PersonCitationMixin, TimestampMixin, Base):
    __tablename__ = "person_events"
    __table_args__ = (
        *_citation_checks(),
        _check_in("role", PERSON_EVENT_ROLES, "role"),
        UniqueConstraint("person_id", "event_id", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))


class PersonMerge(TimestampMixin, Base):
    """The owner's decision that record ``member_id`` is the same person as ``into_id``.

    Nothing moves: each record keeps its name, claims, citations and labels, and views read
    the linked records as one identity. Undoing sets ``undone_at`` (ADR 0013 amendment 1).
    """

    __tablename__ = "person_merges"
    __table_args__ = (
        CheckConstraint("member_id <> into_id", "not_self"),
        Index(
            "uq_person_merges_active_member", "member_id", unique=True,
            postgresql_where=text("undone_at IS NULL"),
        ),
    )  # fmt: skip

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"))
    into_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    undone_at: Mapped[dt.datetime | None] = mapped_column()


class PersonDistinction(TimestampMixin, Base):
    """The owner's decision that two records are not the same person."""

    __tablename__ = "person_distinctions"
    __table_args__ = (
        CheckConstraint("a_id < b_id", "ordered"),
        UniqueConstraint("a_id", "b_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    a_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"))
    b_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="CASCADE"), index=True)


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


BATCH_STATUSES = ("submitted", "collected", "failed")


class LLMBatch(TimestampMixin, Base):
    """A Message Batches API job (50% price; backfills and backlogs, ADR 0004).

    ``items`` maps each request's custom_id to the document it was built from, so results
    can be stored, retried or quarantined against the right record.
    """

    __tablename__ = "llm_batches"
    __table_args__ = (_check_in("status", BATCH_STATUSES, "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    anthropic_batch_id: Mapped[str] = mapped_column(String(128), unique=True)
    stage: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="submitted", index=True)
    n_requests: Mapped[int] = mapped_column(Integer)
    items: Mapped[dict[str, Any]] = mapped_column(default=dict)  # custom_id -> document_id
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    collected_at: Mapped[dt.datetime | None]
    result_counts: Mapped[dict[str, Any]] = mapped_column(default=dict)


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


INGEST_STATUSES = ("running", "ok", "deferred", "error")


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


# --------------------------------------------------------------------------- Phase 2 pipeline


class EventCluster(TimestampMixin, Base):
    """Events that describe the same incident across documents (corroboration group)."""

    __tablename__ = "event_clusters"
    __table_args__ = (
        CheckConstraint("credibility IS NULL OR credibility BETWEEN 1 AND 6", "cred"),
        CheckConstraint("reliability IS NULL OR reliability IN ('A','B','C','D','E','F')", "rel"),
        _gist("event_clusters", "centroid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_date: Mapped[dt.date] = mapped_column(Date, index=True)
    last_date: Mapped[dt.date] = mapped_column(Date)
    event_type: Mapped[str] = mapped_column(String(64))
    centroid: Mapped[WKBElement | None] = mapped_column(POINT())
    admin1_code: Mapped[str | None] = mapped_column(String(16))
    n_events: Mapped[int] = mapped_column(Integer, default=0)
    n_documents: Mapped[int] = mapped_column(Integer, default=0)
    n_independent_sources: Mapped[int] = mapped_column(Integer, default=0)
    # Admiralty: best source reliability among members + information credibility 1..6.
    reliability: Mapped[str | None] = mapped_column(String(1))
    credibility: Mapped[int | None] = mapped_column(SmallInteger)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    conflicts: Mapped[dict[str, Any]] = mapped_column(default=dict)  # field -> distinct values


class ClusterAssessment(LLMDerivedMixin, TimestampMixin, Base):
    """Analytic judgment on a cluster (Sonnet). ICD 203 language; every claim cites records."""

    __tablename__ = "cluster_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), index=True
    )
    judgment: Mapped[str] = mapped_column(Text)
    likelihood: Mapped[str | None] = mapped_column(String(32))  # ICD 203 expression
    analytic_confidence: Mapped[str | None] = mapped_column(String(16))  # low|moderate|high
    resolved: Mapped[dict[str, Any]] = mapped_column(default=dict)  # field -> resolved value
    cited_document_ids: Mapped[list[int]] = mapped_column(default=list)
    cited_event_ids: Mapped[list[int]] = mapped_column(default=list)


QUARANTINE_STAGES = ("filter", "extract", "analyze")


class LLMQuarantine(TimestampMixin, Base):
    """Model output that failed validation twice, or was refused. Never reaches core tables."""

    __tablename__ = "llm_quarantine"
    __table_args__ = (_check_in("stage", QUARANTINE_STAGES, "stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(16))
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(32))  # validation | refusal | max_tokens | error
    error: Mapped[str | None] = mapped_column(Text)
    raw_output: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=1)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class AcledWeekly(TimestampMixin, Base):
    """ACLED's published weekly aggregates: week x admin1 x sub-event type (ADR 0011).

    ``week`` is the Saturday that starts ACLED's Saturday-to-Friday week. Each imported file
    is a snapshot; the combined series (app.analytics.acled_series) reads the newest one.
    """

    __tablename__ = "acled_weekly"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "week",
            "admin1_code",
            "event_type",
            "sub_event_type",
            name="uq_acled_weekly_snapshot",
        ),
        Index("ix_acled_weekly_week", "week"),
        Index("ix_acled_weekly_admin1", "admin1_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[dt.datetime]
    snapshot_date: Mapped[dt.date] = mapped_column(Date)
    week: Mapped[dt.date] = mapped_column(Date)
    country_iso3: Mapped[str] = mapped_column(String(3))
    admin1_code: Mapped[str] = mapped_column(String(16))
    admin1_name: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64))
    sub_event_type: Mapped[str] = mapped_column(String(128))
    disorder_type: Mapped[str | None] = mapped_column(String(64))
    events: Mapped[int] = mapped_column(Integer)
    fatalities: Mapped[int] = mapped_column(Integer)
    population_exposure: Mapped[int | None] = mapped_column(Integer)


class CrimeIncidence(TimestampMixin, Base):
    """SESNSP municipal crime incidence. Methodology 2015-2025 and 2026+ are not comparable."""

    __tablename__ = "crime_incidence"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "methodology",
            "admin2_code",
            "month",
            "crime_key",
            "snapshot_date",
            name="uq_crime_incidence_snapshot",
        ),
        Index("ix_crime_incidence_month", "month"),
        Index("ix_crime_incidence_admin2", "admin2_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[dt.datetime]
    snapshot_date: Mapped[dt.date] = mapped_column(Date)
    methodology: Mapped[str] = mapped_column(String(16))  # "2015-2025" | "2026"
    month: Mapped[dt.date] = mapped_column(Date)
    admin1_code: Mapped[str] = mapped_column(String(16))
    admin2_code: Mapped[str] = mapped_column(String(16))  # INEGI cvegeo (5 digits)
    crime_type: Mapped[str] = mapped_column(String(128))
    crime_subtype: Mapped[str | None] = mapped_column(String(128))
    modality: Mapped[str | None] = mapped_column(String(128))
    crime_key: Mapped[str] = mapped_column(String(400))  # canonical type|subtype|modality
    value: Mapped[int] = mapped_column(Integer)


LABEL_VERDICTS = ("correct", "incorrect", "partial")


class Label(TimestampMixin, Base):
    """Owner's hand label on one extracted record (precision evaluation, ADR 0004)."""

    __tablename__ = "labels"
    __table_args__ = (
        # Per document: a person is judged once for each document it was extracted from.
        UniqueConstraint(
            "document_id", "target_table", "target_id", "field", name="uq_labels_target"
        ),
        _check_in("verdict", LABEL_VERDICTS, "verdict"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    target_table: Mapped[str] = mapped_column(String(32))  # events | seizures | documents | persons
    target_id: Mapped[int] = mapped_column(BigInteger)
    field: Mapped[str] = mapped_column(String(64), default="")  # "" = whole record
    verdict: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(32))  # version being judged
    # documents/"relevant" labels: the pipeline decision judged ("relevant" | "not_relevant"),
    # frozen at labeling time so later re-filtering cannot flip the label's meaning.
    judged_decision: Mapped[str | None] = mapped_column(String(16))


PLACE_TYPES = ("state", "municipality", "locality")


class Place(Base):
    """Local gazetteer (INEGI) for geocoding without external services."""

    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("source", "code", name="uq_places_source_code"),
        _check_in("place_type", PLACE_TYPES, "place_type"),
        _gist("places", "point"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="inegi")
    code: Mapped[str] = mapped_column(String(16))  # INEGI cvegeo
    place_type: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(256))
    name_normalized: Mapped[str] = mapped_column(String(256), index=True)
    country_iso3: Mapped[str] = mapped_column(String(3), default="MEX")
    admin1_code: Mapped[str] = mapped_column(String(16), index=True)
    admin2_code: Mapped[str | None] = mapped_column(String(16), index=True)
    point: Mapped[WKBElement | None] = mapped_column(POINT())
    population: Mapped[int | None] = mapped_column(Integer)
    urban: Mapped[bool | None] = mapped_column(Boolean)
