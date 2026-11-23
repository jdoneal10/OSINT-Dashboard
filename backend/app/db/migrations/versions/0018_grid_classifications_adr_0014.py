"""grid_classifications: provenance of the ACLED grid pass; "grid" quarantine stage (ADR 0014)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-22 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Values as of this revision (inlined so later model edits never rewrite history).
STATUSES = ("batched", "done", "quarantined")
OLD_STAGES = ("filter", "extract", "analyze")
NEW_STAGES = (*OLD_STAGES, "grid")


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _quarantine_stages(values: tuple[str, ...]) -> None:
    name = op.f("ck_llm_quarantine_stage")
    op.drop_constraint(name, "llm_quarantine", type_="check")
    op.create_check_constraint(name, "llm_quarantine", f"stage IN ({_q(values)})")

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    quoted = _q(STATUSES)
    op.create_table(
        "grid_classifications",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("notes_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence", sa.String(400)),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.Column("llm_model", sa.String(64)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("llm_input_tokens", sa.BigInteger()),
        sa.Column("llm_output_tokens", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),  # fmt: skip
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),  # fmt: skip
        sa.CheckConstraint(f"status IN ({quoted})", name=op.f("ck_grid_classifications_status")),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], ondelete="CASCADE",
            name=op.f("fk_grid_classifications_event_id_events"),
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_grid_classifications")),
    )
    op.create_index(
        op.f("ix_grid_classifications_status"), "grid_classifications", ["status"]
    )
    _quarantine_stages(NEW_STAGES)


def downgrade() -> None:
    op.execute("DELETE FROM llm_quarantine WHERE stage = 'grid'")
    _quarantine_stages(OLD_STAGES)
    op.drop_index(op.f("ix_grid_classifications_status"), "grid_classifications")
    op.drop_table("grid_classifications")
