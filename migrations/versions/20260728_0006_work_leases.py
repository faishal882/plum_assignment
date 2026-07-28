"""Add durable work leasing metadata.

Revision ID: 20260728_0006
Revises: 20260728_0005
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0006"
down_revision: str | None = "20260728_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claim_work_items",
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "claim_work_items",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "claim_work_items",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "claim_work_items",
        sa.Column("last_failure_code", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "claim_work_items_attempt_bounds",
        "claim_work_items",
        "attempt_count >= 0 AND attempt_count <= max_attempts",
    )
    op.create_check_constraint(
        "claim_work_items_max_attempts_positive",
        "claim_work_items",
        "max_attempts > 0",
    )
    op.create_check_constraint(
        "claim_work_items_status_supported",
        "claim_work_items",
        "status IN ('AVAILABLE', 'LEASED', 'COMPLETED', 'SUPERSEDED', 'FAILED')",
    )
    op.create_check_constraint(
        "claim_work_items_lease_consistent",
        "claim_work_items",
        "(status = 'LEASED' AND lease_owner IS NOT NULL "
        "AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
        "(status <> 'LEASED' AND lease_owner IS NULL "
        "AND lease_token IS NULL AND lease_until IS NULL)",
    )
    op.create_index(
        "ix_claim_work_items_due",
        "claim_work_items",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_claim_work_items_lease_until",
        "claim_work_items",
        ["lease_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_claim_work_items_lease_until", table_name="claim_work_items")
    op.drop_index("ix_claim_work_items_due", table_name="claim_work_items")
    op.drop_constraint(
        "claim_work_items_lease_consistent",
        "claim_work_items",
        type_="check",
    )
    op.drop_constraint(
        "claim_work_items_status_supported",
        "claim_work_items",
        type_="check",
    )
    op.drop_constraint(
        "claim_work_items_max_attempts_positive",
        "claim_work_items",
        type_="check",
    )
    op.drop_constraint(
        "claim_work_items_attempt_bounds",
        "claim_work_items",
        type_="check",
    )
    op.drop_column("claim_work_items", "last_failure_code")
    op.drop_column("claim_work_items", "lease_until")
    op.drop_column("claim_work_items", "lease_token")
    op.drop_column("claim_work_items", "lease_owner")
