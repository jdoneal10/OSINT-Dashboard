"""seizures.low_priority: small drug amounts and contraband (owner priority framework)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-19 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows start at false; `python -m app.enrich.extract --reprioritize` sets them.
    op.add_column(
        "seizures",
        sa.Column("low_priority", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("seizures", "low_priority")
