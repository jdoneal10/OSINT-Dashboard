"""acled_weekly: ACLED weekly aggregates by admin1 and sub-event type (ADR 0011)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-16 13:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "acled_weekly",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("country_iso3", sa.String(length=3), nullable=False),
        sa.Column("admin1_code", sa.String(length=16), nullable=False),
        sa.Column("admin1_name", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("sub_event_type", sa.String(length=128), nullable=False),
        sa.Column("disorder_type", sa.String(length=64), nullable=True),
        sa.Column("events", sa.Integer(), nullable=False),
        sa.Column("fatalities", sa.Integer(), nullable=False),
        sa.Column("population_exposure", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_acled_weekly_source_id_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acled_weekly")),
        sa.UniqueConstraint(
            "snapshot_date",
            "week",
            "admin1_code",
            "event_type",
            "sub_event_type",
            name="uq_acled_weekly_snapshot",
        ),
    )
    op.create_index("ix_acled_weekly_week", "acled_weekly", ["week"], unique=False)
    op.create_index("ix_acled_weekly_admin1", "acled_weekly", ["admin1_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_acled_weekly_admin1", table_name="acled_weekly")
    op.drop_index("ix_acled_weekly_week", table_name="acled_weekly")
    op.drop_table("acled_weekly")
