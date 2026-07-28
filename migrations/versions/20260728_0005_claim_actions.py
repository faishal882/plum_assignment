"""Add versioned claim actions.

Revision ID: 20260728_0005
Revises: 20260728_0004
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0005"
down_revision: str | None = "20260728_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claim_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column("result_version", sa.Integer(), nullable=False),
        sa.Column("result_lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("replacement_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "replacement_document_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("replacement_document_version", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name="claim_actions_claim_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_document_id"],
            ["documents.id"],
            name="claim_actions_replacement_document_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_document_version_id"],
            ["document_versions.id"],
            name="claim_actions_replacement_document_version_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_user_id"],
            ["users.id"],
            name="claim_actions_scope_user_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replacement_document_version_id",
            name="claim_actions_replacement_document_version_id_key",
        ),
        sa.UniqueConstraint(
            "scope_user_id",
            "claim_id",
            "idempotency_key",
            name="claim_actions_user_claim_key_uq",
        ),
    )
    op.create_index(
        "ix_claim_actions_claim_id",
        "claim_actions",
        ["claim_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_claim_actions_claim_id", table_name="claim_actions")
    op.drop_table("claim_actions")
