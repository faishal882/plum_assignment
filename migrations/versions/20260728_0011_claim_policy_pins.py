"""Pin policy and member snapshots on claims.

Revision ID: 20260728_0011
Revises: 20260728_0010
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0011"
down_revision: str | None = "20260728_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column_name in (
        "policy_source_id",
        "policy_overlay_id",
        "policy_version_id",
        "member_version_id",
    ):
        op.add_column(
            "claims",
            sa.Column(column_name, postgresql.UUID(as_uuid=True), nullable=True),
        )
    op.create_foreign_key(
        "claims_policy_source_id_fkey",
        "claims",
        "policy_sources",
        ["policy_source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "claims_policy_overlay_id_fkey",
        "claims",
        "policy_overlays",
        ["policy_overlay_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "claims_policy_version_id_fkey",
        "claims",
        "policy_versions",
        ["policy_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "claims_member_version_id_fkey",
        "claims",
        "member_versions",
        ["member_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_claims_policy_version_id",
        "claims",
        ["policy_version_id"],
    )
    op.create_index(
        "ix_claims_member_version_id",
        "claims",
        ["member_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_claims_member_version_id", table_name="claims")
    op.drop_index("ix_claims_policy_version_id", table_name="claims")
    for constraint_name in (
        "claims_member_version_id_fkey",
        "claims_policy_version_id_fkey",
        "claims_policy_overlay_id_fkey",
        "claims_policy_source_id_fkey",
    ):
        op.drop_constraint(constraint_name, "claims", type_="foreignkey")
    for column_name in (
        "member_version_id",
        "policy_version_id",
        "policy_overlay_id",
        "policy_source_id",
    ):
        op.drop_column("claims", column_name)
