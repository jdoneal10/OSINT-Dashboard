"""uxs_classifications and uxs_labels: the ACLED UxS pass and its owner labels; "uxs"
quarantine stage (ADR 0009 amendment 1)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-23 20:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# Values as of this revision (inlined so later model edits never rewrite history).
STATUSES = ("batched", "done", "quarantined")
OLD_STAGES = ("filter", "extract", "analyze", "grid")
NEW_STAGES = (*OLD_STAGES, "uxs")
VERDICTS = ("correct", "incorrect", "partial")
ACTIVITIES = (
    "employment", "recovery_or_seizure", "procurement_or_import", "assembly_or_modification",
    "training", "prosecution",
)  # fmt: skip
PLATFORMS = (
    "suas_multirotor", "fpv", "fixed_wing", "heavy_lift_or_hybrid", "ugv", "usv", "unknown",
)  # fmt: skip
MISSIONS = (
    "surveillance", "route_security", "overwatch", "attack", "logistics",
    "coercion_or_propaganda", "surveillance_of_security_forces", "monitoring_economic_activity",
)  # fmt: skip
PAYLOADS = (
    "explosive_or_grenade", "ied", "camera_or_thermal", "release_mechanism", "supply",
    "loudspeaker_or_light", "none_reported",
)  # fmt: skip
LABEL_ITEMS = ("activity", "platform", *MISSIONS, *PAYLOADS)

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _q(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _quarantine_stages(values: tuple[str, ...]) -> None:
    name = op.f("ck_llm_quarantine_stage")
    op.drop_constraint(name, "llm_quarantine", type_="check")
    op.create_check_constraint(name, "llm_quarantine", f"stage IN ({_q(values)})")


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]  # fmt: skip


def upgrade() -> None:
    op.create_table(
        "uxs_classifications",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("notes_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence", sa.String(400)),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.Column("llm_model", sa.String(64)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("llm_input_tokens", sa.BigInteger()),
        sa.Column("llm_output_tokens", sa.BigInteger()),
        *_timestamps(),
        sa.CheckConstraint(
            f"status IN ({_q(STATUSES)})", name=op.f("ck_uxs_classifications_status")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], ondelete="CASCADE",
            name=op.f("fk_uxs_classifications_event_id_events"),
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_uxs_classifications")),
    )
    op.create_index(op.f("ix_uxs_classifications_status"), "uxs_classifications", ["status"])
    _quarantine_stages(NEW_STAGES)
    op.create_table(
        "uxs_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("wrong", ARRAY(sa.String(40)), server_default="{}", nullable=False),
        sa.Column("judged_activity", sa.String(32), nullable=False),
        sa.Column("judged_platform", sa.String(32), nullable=False),
        sa.Column("judged_missions", ARRAY(sa.String(40)), server_default="{}", nullable=False),
        sa.Column("judged_payloads", ARRAY(sa.String(40)), server_default="{}", nullable=False),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("note", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(f"verdict IN ({_q(VERDICTS)})", name=op.f("ck_uxs_labels_verdict")),
        sa.CheckConstraint(
            f"judged_activity IN ({_q(ACTIVITIES)})", name=op.f("ck_uxs_labels_judged_activity")
        ),
        sa.CheckConstraint(
            f"judged_platform IN ({_q(PLATFORMS)})", name=op.f("ck_uxs_labels_judged_platform")
        ),
        sa.CheckConstraint(
            f"judged_missions <@ ARRAY[{_q(MISSIONS)}]::varchar[]",
            name=op.f("ck_uxs_labels_judged_missions"),
        ),
        sa.CheckConstraint(
            f"judged_payloads <@ ARRAY[{_q(PAYLOADS)}]::varchar[]",
            name=op.f("ck_uxs_labels_judged_payloads"),
        ),
        sa.CheckConstraint(
            f"wrong <@ ARRAY[{_q(LABEL_ITEMS)}]::varchar[]", name=op.f("ck_uxs_labels_wrong")
        ),
        sa.CheckConstraint(
            "(verdict = 'partial') = (cardinality(wrong) > 0)",
            name=op.f("ck_uxs_labels_partial_names_items"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], ondelete="CASCADE",
            name=op.f("fk_uxs_labels_event_id_events"),
        ),  # fmt: skip
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uxs_labels")),
        sa.UniqueConstraint("event_id", name=op.f("uq_uxs_labels_event_id")),
    )


def downgrade() -> None:
    op.drop_table("uxs_labels")
    op.execute("DELETE FROM llm_quarantine WHERE stage = 'uxs'")
    _quarantine_stages(OLD_STAGES)
    op.drop_index(op.f("ix_uxs_classifications_status"), "uxs_classifications")
    op.drop_table("uxs_classifications")
