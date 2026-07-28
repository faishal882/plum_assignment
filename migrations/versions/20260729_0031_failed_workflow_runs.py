"""Represent exhausted processing as failed workflow runs.

Revision ID: 20260729_0031
Revises: 20260729_0030
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0031"
down_revision: str | None = "20260729_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("workflow_runs_status_supported", "workflow_runs", type_="check")
    op.create_check_constraint(
        "workflow_runs_status_supported",
        "workflow_runs",
        "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint("workflow_runs_status_supported", "workflow_runs", type_="check")
    op.create_check_constraint(
        "workflow_runs_status_supported",
        "workflow_runs",
        "status IN ('PENDING', 'RUNNING', 'COMPLETED')",
    )
