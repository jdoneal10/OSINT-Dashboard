"""labels.judged_decision: freeze the relevance decision a label judged

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 19:00:00

A relevance label says whether the pipeline's decision was right. Without the decision itself
the label's meaning flips when a document is re-filtered. Existing labels are backfilled from
the documents' current status (no document has been re-processed since it was labeled).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("labels", sa.Column("judged_decision", sa.String(16), nullable=True))
    op.execute(
        """
        UPDATE labels l
           SET judged_decision = CASE WHEN d.pipeline_status = 'extracted'
                                      THEN 'relevant' ELSE 'not_relevant' END
          FROM documents d
         WHERE l.target_table = 'documents' AND l.field = 'relevant' AND d.id = l.document_id
        """
    )


def downgrade() -> None:
    op.drop_column("labels", "judged_decision")
