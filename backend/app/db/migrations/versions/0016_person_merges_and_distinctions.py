"""reviewed person merges and "not the same person" decisions (ADR 0013 amendment 1)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-22 07:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "person_merges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("into_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("member_id <> into_id", name=op.f("ck_person_merges_not_self")),
        sa.ForeignKeyConstraint(
            ["member_id"], ["persons.id"], ondelete="CASCADE",
            name=op.f("fk_person_merges_member_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["into_id"], ["persons.id"], ondelete="CASCADE",
            name=op.f("fk_person_merges_into_id_persons"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_merges")),
    )
    op.create_index(op.f("ix_person_merges_into_id"), "person_merges", ["into_id"])
    op.create_index(
        "uq_person_merges_active_member", "person_merges", ["member_id"], unique=True,
        postgresql_where=sa.text("undone_at IS NULL"),
    )
    op.create_table(
        "person_distinctions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("a_id", sa.Integer(), nullable=False),
        sa.Column("b_id", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("a_id < b_id", name=op.f("ck_person_distinctions_ordered")),
        sa.ForeignKeyConstraint(
            ["a_id"], ["persons.id"], ondelete="CASCADE",
            name=op.f("fk_person_distinctions_a_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["b_id"], ["persons.id"], ondelete="CASCADE",
            name=op.f("fk_person_distinctions_b_id_persons"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_distinctions")),
        sa.UniqueConstraint("a_id", "b_id", name=op.f("uq_person_distinctions_a_id_b_id")),
    )
    op.create_index(op.f("ix_person_distinctions_b_id"), "person_distinctions", ["b_id"])


def downgrade() -> None:
    op.drop_table("person_distinctions")
    op.drop_table("person_merges")
