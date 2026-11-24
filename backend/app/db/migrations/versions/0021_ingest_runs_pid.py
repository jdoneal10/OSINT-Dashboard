"""ingest_runs.pid: the process that started a run, so runs left "running" by an ended
process can be closed when the worker starts

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-24 06:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingest_runs", sa.Column("pid", sa.Integer()))


def downgrade() -> None:
    op.drop_column("ingest_runs", "pid")
