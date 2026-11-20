"""in_aoi flag on events and seizures

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11 18:10:00

News-derived records placed outside the current AOI are kept but hidden by default (ADR 0004).
Existing rows default to true; re-run extraction to flag earlier news-derived records.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("events", "seizures"):
        op.add_column(
            table, sa.Column("in_aoi", sa.Boolean(), server_default=sa.true(), nullable=False)
        )


def downgrade() -> None:
    for table in ("events", "seizures"):
        op.drop_column(table, "in_aoi")
