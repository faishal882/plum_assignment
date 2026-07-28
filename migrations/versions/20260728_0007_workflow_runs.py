"""Add workflow runs and normalized work versions.

Revision ID: 20260728_0007
Revises: 20260728_0006
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0007"
down_revision: str | None = "20260728_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claim_work_items",
        sa.Column("claim_version", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE claim_work_items
        SET claim_version = regexp_replace(operation_key, '^.*v([0-9]+)$', '\\1')::integer
        """
    )
    op.alter_column("claim_work_items", "claim_version", nullable=False)
    op.create_check_constraint(
        "claim_work_items_claim_version_positive",
        "claim_work_items",
        "claim_version > 0",
    )
    op.create_foreign_key(
        "claim_work_items_claim_version_fkey",
        "claim_work_items",
        "claim_versions",
        ["claim_id", "claim_version"],
        ["claim_id", "version"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(length=160), nullable=False),
        sa.Column("graph_name", sa.String(length=64), nullable=False),
        sa.Column("graph_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "claim_version > 0",
            name="workflow_runs_claim_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED')",
            name="workflow_runs_status_supported",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name="workflow_runs_claim_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id", "claim_version"],
            ["claim_versions.claim_id", "claim_versions.version"],
            name="workflow_runs_claim_version_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["work_item_id"],
            ["claim_work_items.id"],
            name="workflow_runs_work_item_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_key", name="workflow_runs_operation_key_key"),
        sa.UniqueConstraint("work_item_id", name="workflow_runs_work_item_id_key"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            "graph_name",
            "graph_version",
            name="workflow_runs_claim_graph_version_uq",
        ),
    )
    op.create_index(
        "ix_workflow_runs_claim_id",
        "workflow_runs",
        ["claim_id"],
        unique=False,
    )
    op.create_table(
        "workflow_effects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effect_key", sa.String(length=160), nullable=False),
        sa.Column("effect_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="workflow_effects_workflow_run_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "effect_key",
            name="workflow_effects_run_key_uq",
        ),
    )
    op.create_index(
        "ix_workflow_effects_workflow_run_id",
        "workflow_effects",
        ["workflow_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_effects_workflow_run_id",
        table_name="workflow_effects",
    )
    op.drop_table("workflow_effects")
    op.drop_index("ix_workflow_runs_claim_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_constraint(
        "claim_work_items_claim_version_fkey",
        "claim_work_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "claim_work_items_claim_version_positive",
        "claim_work_items",
        type_="check",
    )
    op.drop_column("claim_work_items", "claim_version")
