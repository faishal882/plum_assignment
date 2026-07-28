"""Add readability provenance and structured action details.

Revision ID: 20260728_0016
Revises: 20260728_0015
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0016"
down_revision: str | None = "20260728_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_triage_results",
        sa.Column(
            "readability_observation",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column(
        "document_triage_results",
        "readability_observation",
        server_default=None,
    )
    op.add_column(
        "member_actions",
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("member_actions", "details", server_default=None)


def downgrade() -> None:
    op.drop_column("member_actions", "details")
    op.drop_column("document_triage_results", "readability_observation")
