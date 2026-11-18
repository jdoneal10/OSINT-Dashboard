"""sources.source_type: add 'email' (Dataminr First Alert digests, ADR 0012)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-17 12:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAME = "ck_sources_source_type"
OLD = "'api', 'dataset', 'rss', 'web', 'reference'"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "sources", type_="check")
    op.create_check_constraint(op.f(NAME), "sources", f"source_type IN ({OLD}, 'email')")


def downgrade() -> None:
    op.drop_constraint(op.f(NAME), "sources", type_="check")
    op.create_check_constraint(op.f(NAME), "sources", f"source_type IN ({OLD})")
