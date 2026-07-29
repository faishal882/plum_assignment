"""Persist grounded document triage evidence references.

Revision ID: 20260729_0036
Revises: 20260729_0035
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0036"
down_revision: str | None = "20260729_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_triage_results",
        sa.Column(
            "role_evidence_refs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_triage_results",
        sa.Column(
            "readability_evidence_refs",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_triage_results", "readability_evidence_refs")
    op.drop_column("document_triage_results", "role_evidence_refs")
