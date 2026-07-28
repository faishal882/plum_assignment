"""Add bounded document triage and member actions.

Revision ID: 20260728_0014
Revises: 20260728_0013
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0014"
down_revision: str | None = "20260728_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_triage_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_document_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("readability", sa.String(length=32), nullable=False),
        sa.Column("identity_observations", postgresql.JSONB(), nullable=False),
        sa.Column("model_route", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            "client_document_id",
            name="document_triage_results_claim_version_document_uq",
        ),
    )
    op.create_index(
        "ix_document_triage_results_claim_id",
        "document_triage_results",
        ["claim_id"],
    )
    op.create_table(
        "member_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_document_roles", postgresql.JSONB(), nullable=False),
        sa.Column("required_document_roles", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="member_actions_claim_version_uq",
        ),
    )
    op.create_index("ix_member_actions_claim_id", "member_actions", ["claim_id"])


def downgrade() -> None:
    op.drop_table("member_actions")
    op.drop_table("document_triage_results")
