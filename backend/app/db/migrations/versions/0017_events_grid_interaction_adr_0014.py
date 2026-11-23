"""events: reported grid interactions and energy indicators (ADR 0014)

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-22 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# Values as of this revision (inlined so later model edits never rewrite history).
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

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.add_column("events", sa.Column("grid_interaction", sa.String(40)))
    op.add_column(
        "events",
        sa.Column("energy_indicators", ARRAY(sa.String(40)), server_default="{}", nullable=False),
    )
    # Existing theft cases (energy_method set) become grid_interaction 'theft'.
    op.execute("UPDATE events SET grid_interaction = 'theft' WHERE energy_method IS NOT NULL")
    op.create_index(op.f("ix_events_grid_interaction"), "events", ["grid_interaction"])
    op.create_check_constraint(
        op.f("ck_events_grid_interaction"),
        "events",
        f"grid_interaction IS NULL OR grid_interaction IN ({_q(GRID_INTERACTIONS)})",
    )
    op.create_check_constraint(
        op.f("ck_events_energy_indicators"),
        "events",
        f"energy_indicators <@ ARRAY[{_q(ENERGY_INDICATORS)}]::varchar[]",
    )
    op.create_check_constraint(
        op.f("ck_events_grid_theft_detail"),
        "events",
        "(energy_method IS NOT NULL) = (grid_interaction IS NOT DISTINCT FROM 'theft')",
    )


def downgrade() -> None:
    for name in ("grid_theft_detail", "energy_indicators", "grid_interaction"):
        op.drop_constraint(op.f(f"ck_events_{name}"), "events", type_="check")
    op.drop_index(op.f("ix_events_grid_interaction"), "events")
    op.drop_column("events", "energy_indicators")
    op.drop_column("events", "grid_interaction")
