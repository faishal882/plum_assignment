"""Add durable human review workflow tables.

Revision ID: 20260728_0025
Revises: 20260728_0024
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0025"
down_revision: str | None = "20260728_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("handling_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("review_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_table(
        "review_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column(
            "decision_record_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("signal_codes", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_actions", postgresql.JSONB(), nullable=False),
        sa.Column("machine_recommendation", sa.String(length=32), nullable=False),
        sa.Column("machine_approved_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "machine_approved_paise >= 0",
            name="review_tasks_machine_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')",
            name="review_tasks_status_supported",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_record_id"],
            ["decision_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="review_tasks_claim_version_uq",
        ),
        sa.UniqueConstraint("decision_record_id"),
    )
    op.create_index(
        "ix_review_tasks_claim_id",
        "review_tasks",
        ["claim_id"],
    )
    op.create_table(
        "review_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_username_snapshot", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["review_tasks.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_user_id",
            "task_id",
            "idempotency_key",
            name="review_resolutions_actor_task_key_uq",
        ),
        sa.UniqueConstraint("task_id", name="review_resolutions_task_uq"),
    )
    op.create_foreign_key(
        "claims_review_task_fk",
        "claims",
        "review_tasks",
        ["review_task_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint("claims_review_task_fk", "claims", type_="foreignkey")
    op.drop_table("review_resolutions")
    op.drop_index("ix_review_tasks_claim_id", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_column("claims", "review_task_id")
    op.drop_column("claims", "handling_status")
