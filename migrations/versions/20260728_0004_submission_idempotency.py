"""Add atomic claim submission idempotency.

Revision ID: 20260728_0004
Revises: 20260728_0003
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0004"
down_revision: str | None = "20260728_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["response_claim_id"],
            ["claims.id"],
            name="idempotency_keys_response_claim_id_fkey",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["scope_user_id"],
            ["users.id"],
            name="idempotency_keys_scope_user_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "response_claim_id",
            name="idempotency_keys_response_claim_id_key",
        ),
        sa.UniqueConstraint(
            "scope_user_id",
            "idempotency_key",
            name="idempotency_keys_user_key_uq",
        ),
    )
    op.create_index(
        "ix_idempotency_keys_scope_user_id",
        "idempotency_keys",
        ["scope_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_scope_user_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
