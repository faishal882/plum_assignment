"""Persist triage evidence-normalization audit data.

Revision ID: 20260729_0037
Revises: 20260729_0036
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0037"
down_revision: str | None = "20260729_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_triage_results",
        sa.Column("normalization_report", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "document_triage_results",
        sa.Column("raw_provider_output_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_triage_results", "raw_provider_output_sha256")
    op.drop_column("document_triage_results", "normalization_report")
