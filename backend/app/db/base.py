"""Declarative base, naming conventions and shared column mixins."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 — SQLAlchemy reads this class attribute
        dict[str, Any]: JSONB,
        list[dict[str, Any]]: JSONB,
        list[str]: JSONB,
        dt.datetime: DateTime(timezone=True),
    }


def provenance_table_args(table: str) -> tuple[CheckConstraint | UniqueConstraint, ...]:
    """Constraints every ``ProvenanceMixin`` table carries: value checks + the upsert key."""
    return (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", "conf"),
        CheckConstraint("credibility IS NULL OR credibility BETWEEN 1 AND 6", "cred"),
        UniqueConstraint("source_id", "source_key", name=f"uq_{table}_source_key"),
    )


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProvenanceMixin:
    """Provenance required on every source-derived record (CLAUDE.md conventions).

    ``(source_id, source_key)`` is the stable upsert key that keeps ingesters idempotent
    (enforced by :func:`provenance_table_args`).
    ``confidence`` is 0..1; ``credibility`` is the Admiralty information-credibility grade 1..6
    (source reliability A..F lives on ``sources``).
    """

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[dt.datetime]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    credibility: Mapped[int | None] = mapped_column(Integer)


class LLMDerivedMixin:
    """Columns stored with every LLM-derived record (CLAUDE.md LLM pipeline rules)."""

    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    llm_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    llm_output_tokens: Mapped[int | None] = mapped_column(BigInteger)
