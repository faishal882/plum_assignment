"""Add immutable patient identity reconciliations.

Revision ID: 20260728_0017
Revises: 20260728_0016
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0017"
down_revision: str | None = "20260728_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_reconciliations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("member_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("member_name", sa.String(length=128), nullable=False),
        sa.Column("candidates", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["member_version_id"],
            ["member_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="identity_reconciliations_claim_version_uq",
        ),
    )
    op.create_index(
        "ix_identity_reconciliations_claim_id",
        "identity_reconciliations",
        ["claim_id"],
    )
    op.execute(
        """
        CREATE TRIGGER identity_reconciliations_immutable
        BEFORE UPDATE OR DELETE ON identity_reconciliations
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER identity_reconciliations_immutable ON identity_reconciliations")
    op.drop_table("identity_reconciliations")
