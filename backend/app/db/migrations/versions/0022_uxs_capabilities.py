"""events.uxs_capabilities and uxs_labels.judged_capabilities: ladder rungs 6-8 a source
reports (coordinated multi-UxS operations, relays or repeaters, autonomy; ADR 0009
amendment 2)

Both start empty, so every existing UxS label stays current.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-25 21:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# Values as of this revision (inlined so later model edits never rewrite history).
CAPABILITIES = ("coordinated_multi_uxs", "relay_or_repeater", "autonomy")
MISSIONS = (
    "surveillance", "route_security", "overwatch", "attack", "logistics",
    "coercion_or_propaganda", "surveillance_of_security_forces", "monitoring_economic_activity",
)  # fmt: skip
PAYLOADS = (
    "explosive_or_grenade", "ied", "camera_or_thermal", "release_mechanism", "supply",
    "loudspeaker_or_light", "none_reported",
)  # fmt: skip
OLD_LABEL_ITEMS = ("activity", "platform", *MISSIONS, *PAYLOADS)
NEW_LABEL_ITEMS = (*OLD_LABEL_ITEMS, *CAPABILITIES)

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _array(table: str, column: str) -> None:
    op.add_column(
        table, sa.Column(column, ARRAY(sa.String(40)), server_default="{}", nullable=False)
    )
    op.create_check_constraint(
        op.f(f"ck_{table}_{column}"), table, f"{column} <@ ARRAY[{_q(CAPABILITIES)}]::varchar[]"
    )


def _wrong(items: tuple[str, ...]) -> None:
    name = op.f("ck_uxs_labels_wrong")
    op.drop_constraint(name, "uxs_labels", type_="check")
    op.create_check_constraint(name, "uxs_labels", f"wrong <@ ARRAY[{_q(items)}]::varchar[]")


def upgrade() -> None:
    _array("events", "uxs_capabilities")
    _array("uxs_labels", "judged_capabilities")
    _wrong(NEW_LABEL_ITEMS)


def downgrade() -> None:
    _wrong(OLD_LABEL_ITEMS)
    op.drop_column("uxs_labels", "judged_capabilities")
    op.drop_column("events", "uxs_capabilities")
