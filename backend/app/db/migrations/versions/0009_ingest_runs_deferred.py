"""ingest_runs.status: add 'deferred' (upstream refused, next run's window covers it)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16 12:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "ck_ingest_runs_status"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "ingest_runs", type_="check")
    op.create_check_constraint(
        op.f(NAME), "ingest_runs", "status IN ('running', 'ok', 'deferred', 'error')"
    )


def downgrade() -> None:
    op.execute("UPDATE ingest_runs SET status = 'error' WHERE status = 'deferred'")
    op.drop_constraint(op.f(NAME), "ingest_runs", type_="check")
    op.create_check_constraint(op.f(NAME), "ingest_runs", "status IN ('running', 'ok', 'error')")
