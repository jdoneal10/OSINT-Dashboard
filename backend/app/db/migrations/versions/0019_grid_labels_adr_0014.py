"""grid_labels: owner labels on grid verdicts, for ACLED and news events (ADR 0014 step 6)

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-23 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# Values as of this revision (inlined so later model edits never rewrite history).
VERDICTS = ("correct", "incorrect", "partial")
GRID_INTERACTIONS = (
    "theft",
    "deliberate_outage_or_sabotage",
    "attack_on_utility_workers",
    "extortion_or_service_control",
    "infrastructure_theft",
    "utility_withdrawal",
)
ENERGY_INDICATORS = (
    "mining_equipment_seized",
    "high_load_site",
    "outage_in_contested_area",
    "utility_insider_reported",
    "fuel_theft",
)
LABEL_ITEMS = ("kind", *ENERGY_INDICATORS)

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "grid_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("wrong", ARRAY(sa.String(40)), server_default="{}", nullable=False),
        sa.Column("judged_kind", sa.String(40)),
        sa.Column("judged_indicators", ARRAY(sa.String(40)), server_default="{}",
                  nullable=False),  # fmt: skip
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),  # fmt: skip
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),  # fmt: skip
        sa.CheckConstraint(f"verdict IN ({_q(VERDICTS)})", name=op.f("ck_grid_labels_verdict")),
        sa.CheckConstraint(
            f"judged_kind IN ({_q(GRID_INTERACTIONS)})", name=op.f("ck_grid_labels_judged_kind")
        ),
        sa.CheckConstraint(
            f"judged_indicators <@ ARRAY[{_q(ENERGY_INDICATORS)}]::varchar[]",
            name=op.f("ck_grid_labels_judged_indicators"),
        ),
        sa.CheckConstraint(
            f"wrong <@ ARRAY[{_q(LABEL_ITEMS)}]::varchar[]", name=op.f("ck_grid_labels_wrong")
        ),
        sa.CheckConstraint(
            "(verdict = 'partial') = (cardinality(wrong) > 0)",
            name=op.f("ck_grid_labels_partial_names_items"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], ondelete="CASCADE",
            name=op.f("fk_grid_labels_event_id_events"),
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grid_labels")),
        sa.UniqueConstraint("event_id", name=op.f("uq_grid_labels_event_id")),
    )


def downgrade() -> None:
    op.drop_table("grid_labels")
