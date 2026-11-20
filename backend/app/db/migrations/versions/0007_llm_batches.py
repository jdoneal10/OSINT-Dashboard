"""llm_batches table; documents.pipeline_status gains 'batched'

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12 10:00:00

Extraction backlogs (backfills, re-extraction after a prompt change) go through the Message
Batches API at half price. A document waiting on a batch is 'batched'.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "('new', 'filtered_out', 'relevant', 'extracted', 'quarantined', 'skipped')"
NEW = "('new', 'filtered_out', 'relevant', 'batched', 'extracted', 'quarantined', 'skipped')"


def upgrade() -> None:
    op.create_table(
        "llm_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anthropic_batch_id", sa.String(length=128), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("n_requests", sa.Integer(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('submitted', 'collected', 'failed')", name=op.f("ck_llm_batches_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_batches")),
        sa.UniqueConstraint("anthropic_batch_id", name=op.f("uq_llm_batches_anthropic_batch_id")),
    )
    op.create_index(op.f("ix_llm_batches_status"), "llm_batches", ["status"], unique=False)
    op.drop_constraint(op.f("ck_documents_pipeline_status"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_pipeline_status"), "documents", f"pipeline_status IN {NEW}"
    )


def downgrade() -> None:
    op.execute("UPDATE documents SET pipeline_status = 'relevant' WHERE pipeline_status = 'batched'")
    op.drop_constraint(op.f("ck_documents_pipeline_status"), "documents", type_="check")
    op.create_check_constraint(
        op.f("ck_documents_pipeline_status"), "documents", f"pipeline_status IN {OLD}"
    )
    op.drop_index(op.f("ix_llm_batches_status"), table_name="llm_batches")
    op.drop_table("llm_batches")
