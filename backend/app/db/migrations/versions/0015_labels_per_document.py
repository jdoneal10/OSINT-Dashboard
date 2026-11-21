"""labels: unique per document, so persons can be labeled per document (ADR 0013)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-20 18:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_labels_target", "labels", type_="unique")
    op.create_unique_constraint(
        "uq_labels_target", "labels", ["document_id", "target_table", "target_id", "field"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_labels_target", "labels", type_="unique")
    op.create_unique_constraint("uq_labels_target", "labels", ["target_table", "target_id", "field"])
