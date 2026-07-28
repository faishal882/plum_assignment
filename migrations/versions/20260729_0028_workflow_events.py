"""Add ordered workflow observability events.

Revision ID: 20260729_0028
Revises: 20260729_0027
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0028"
down_revision: str | None = "20260729_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name="workflow_events_sequence_positive"),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="workflow_events_attempt_positive",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="workflow_events_duration_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "sequence",
            name="workflow_events_run_sequence_uq",
        ),
    )
    op.create_index(
        "ix_workflow_events_workflow_run_id",
        "workflow_events",
        ["workflow_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_workflow_run_id", table_name="workflow_events")
    op.drop_table("workflow_events")
