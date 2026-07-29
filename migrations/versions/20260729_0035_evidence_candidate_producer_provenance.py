"""Persist the producer-specific evidence decoder contract.

Revision ID: 20260729_0035
Revises: 20260729_0034
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0035"
down_revision: str | None = "20260729_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER evidence_candidates_immutable ON evidence_candidates")
    op.add_column(
        "evidence_candidates",
        sa.Column("producer_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "evidence_candidates",
        sa.Column("candidate_schema_version", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE evidence_candidates AS candidate
        SET producer_version = extraction.model_id || ':' || extraction.prompt_version,
            candidate_schema_version = extraction.schema_version
        FROM model_extractions AS extraction
        WHERE extraction.id = candidate.model_extraction_id
        """
    )
    op.alter_column("evidence_candidates", "producer_version", nullable=False)
    op.alter_column("evidence_candidates", "candidate_schema_version", nullable=False)
    op.execute(
        """
        CREATE TRIGGER evidence_candidates_immutable
        BEFORE UPDATE OR DELETE ON evidence_candidates
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER evidence_candidates_immutable ON evidence_candidates")
    op.drop_column("evidence_candidates", "candidate_schema_version")
    op.drop_column("evidence_candidates", "producer_version")
    op.execute(
        """
        CREATE TRIGGER evidence_candidates_immutable
        BEFORE UPDATE OR DELETE ON evidence_candidates
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )
