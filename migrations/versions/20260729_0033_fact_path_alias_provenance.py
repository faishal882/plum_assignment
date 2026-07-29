"""Persist canonical fact-path alias provenance.

Revision ID: 20260729_0033
Revises: 20260729_0032
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0033"
down_revision: str | None = "20260729_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER evidence_candidates_immutable ON evidence_candidates")
    op.add_column(
        "evidence_candidates",
        sa.Column("source_fact_path", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "evidence_candidates",
        sa.Column("alias_registry_version", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE evidence_candidates SET source_fact_path = fact_path")
    op.alter_column("evidence_candidates", "source_fact_path", nullable=False)
    op.execute(
        """
        CREATE TRIGGER evidence_candidates_immutable
        BEFORE UPDATE OR DELETE ON evidence_candidates
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER evidence_candidates_immutable ON evidence_candidates")
    op.drop_column("evidence_candidates", "alias_registry_version")
    op.drop_column("evidence_candidates", "source_fact_path")
    op.execute(
        """
        CREATE TRIGGER evidence_candidates_immutable
        BEFORE UPDATE OR DELETE ON evidence_candidates
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )
