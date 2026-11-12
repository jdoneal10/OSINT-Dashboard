"""Phase 1: event location/precision fields, raw attributes, ACLED role vocabulary,
OFO field-office node type.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

Hand-written: autogenerate does not detect CHECK-constraint changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NODE_TYPES_OLD = (
    "poe",
    "usbp_sector",
    "seaport",
    "airport",
    "lab_region",
    "transit_hub",
    "crossing",
)
NODE_TYPES_NEW = ("poe", "usbp_sector", "ofo_field_office", *NODE_TYPES_OLD[2:])
ROLES_OLD = ("perpetrator", "target", "other")
ROLES_NEW = (*ROLES_OLD, "actor1", "actor2", "assoc_actor1", "assoc_actor2")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("events", sa.Column("time_precision", sa.SmallInteger(), nullable=True))
    op.add_column("events", sa.Column("admin1_name", sa.String(length=128), nullable=True))
    op.add_column("events", sa.Column("admin2_name", sa.String(length=128), nullable=True))
    op.add_column("events", sa.Column("location_name", sa.String(length=256), nullable=True))
    op.add_column(
        "events",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("events", "attributes", server_default=None)

    op.drop_constraint(op.f("ck_nodes_node_type"), "nodes", type_="check")
    op.create_check_constraint("node_type", "nodes", _in("node_type", NODE_TYPES_NEW))
    op.drop_constraint(op.f("ck_actor_events_role"), "actor_events", type_="check")
    op.create_check_constraint("role", "actor_events", _in("role", ROLES_NEW))


def downgrade() -> None:
    op.drop_constraint(op.f("ck_actor_events_role"), "actor_events", type_="check")
    op.create_check_constraint("role", "actor_events", _in("role", ROLES_OLD))
    op.drop_constraint(op.f("ck_nodes_node_type"), "nodes", type_="check")
    op.create_check_constraint("node_type", "nodes", _in("node_type", NODE_TYPES_OLD))

    op.drop_column("events", "attributes")
    op.drop_column("events", "location_name")
    op.drop_column("events", "admin2_name")
    op.drop_column("events", "admin1_name")
    op.drop_column("events", "time_precision")
