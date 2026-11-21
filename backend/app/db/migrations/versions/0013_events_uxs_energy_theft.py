"""events: unmanned-systems and electricity-theft fields (extract-v7; ADR 0009)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-20 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY


# Values as of this revision (inlined so later model edits never rewrite history).
UXS_PLATFORMS = ('suas_multirotor', 'fpv', 'fixed_wing', 'heavy_lift_or_hybrid', 'ugv', 'usv', 'unknown')
UXS_MISSIONS = ('surveillance', 'route_security', 'overwatch', 'attack', 'logistics', 'coercion_or_propaganda', 'surveillance_of_security_forces', 'monitoring_economic_activity')
UXS_PAYLOADS = ('explosive_or_grenade', 'ied', 'camera_or_thermal', 'release_mechanism', 'supply', 'loudspeaker_or_light', 'none_reported')
UXS_ACTIVITIES = ('employment', 'recovery_or_seizure', 'procurement_or_import', 'assembly_or_modification', 'training', 'prosecution')
ENERGY_METHODS = ('meter_bypass', 'illegal_line_connection', 'transformer_or_feeder_tampering', 'insider_facilitation', 'unknown')
ENERGY_POWERED = ('crypto_mining', 'cultivation', 'drug_lab', 'warehouse_or_storage', 'refrigeration', 'communications', 'residential_compound', 'other')
ENERGY_FACILITATORS = ('utility_employee', 'contractor', 'electrician', 'official', 'property_manager', 'none_reported')

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


SCALARS = {
    "uxs_platform": UXS_PLATFORMS,
    "uxs_activity": UXS_ACTIVITIES,
    "energy_method": ENERGY_METHODS,
    "energy_facilitator": ENERGY_FACILITATORS,
}
ARRAYS = {
    "uxs_missions": UXS_MISSIONS,
    "uxs_payloads": UXS_PAYLOADS,
    "energy_powered": ENERGY_POWERED,
}
PAIRS = {
    "uxs_complete": ("uxs_activity", "uxs_platform"),
    "energy_theft_complete": ("energy_method", "energy_facilitator"),
}


def upgrade() -> None:
    op.add_column("events", sa.Column("uxs_activity", sa.String(32)))
    op.add_column("events", sa.Column("uxs_platform", sa.String(32)))
    op.add_column("events", sa.Column("energy_method", sa.String(40)))
    op.add_column("events", sa.Column("energy_facilitator", sa.String(32)))
    op.add_column("events", sa.Column("energy_scale", sa.String(200)))
    for name, width in (("uxs_missions", 40), ("uxs_payloads", 40), ("energy_powered", 32)):
        op.add_column(
            "events",
            sa.Column(name, ARRAY(sa.String(width)), server_default="{}", nullable=False),
        )
    op.create_index(op.f("ix_events_uxs_activity"), "events", ["uxs_activity"])
    op.create_index(op.f("ix_events_energy_method"), "events", ["energy_method"])
    for col, values in SCALARS.items():
        op.create_check_constraint(
            op.f(f"ck_events_{col}"), "events", f"{col} IS NULL OR {col} IN ({_q(values)})"
        )
    for col, values in ARRAYS.items():
        op.create_check_constraint(
            op.f(f"ck_events_{col}"), "events", f"{col} <@ ARRAY[{_q(values)}]::varchar[]"
        )
    for name, (a, b) in PAIRS.items():
        op.create_check_constraint(
            op.f(f"ck_events_{name}"), "events", f"({a} IS NULL) = ({b} IS NULL)"
        )


def downgrade() -> None:
    for name in [*SCALARS, *ARRAYS, *PAIRS]:
        op.drop_constraint(op.f(f"ck_events_{name}"), "events", type_="check")
    op.drop_index(op.f("ix_events_energy_method"), "events")
    op.drop_index(op.f("ix_events_uxs_activity"), "events")
    for col in (
        "uxs_activity", "uxs_platform", "uxs_missions", "uxs_payloads",
        "energy_method", "energy_powered", "energy_facilitator", "energy_scale",
    ):  # fmt: skip
        op.drop_column("events", col)
