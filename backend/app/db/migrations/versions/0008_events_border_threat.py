"""events.border_threat: priority border-threat category (ADR 0007)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

THREATS = (
    "human_smuggling",
    "uas_incursion",
    "laser_strike",
    "gunfire",
    "assault_on_personnel",
    "tunnel",
    "other_border_threat",
)


def upgrade() -> None:
    op.add_column("events", sa.Column("border_threat", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_events_border_threat"), "events", ["border_threat"], unique=False)
    op.create_check_constraint(
        op.f("ck_events_border_threat"),
        "events",
        "border_threat IS NULL OR border_threat IN (" + ", ".join(f"'{t}'" for t in THREATS) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_events_border_threat"), "events", type_="check")
    op.drop_index(op.f("ix_events_border_threat"), table_name="events")
    op.drop_column("events", "border_threat")
