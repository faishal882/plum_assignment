"""Add structured adjudication trace and claim projection.

Revision ID: 20260728_0013
Revises: 20260728_0012
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0013"
down_revision: str | None = "20260728_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("adjudication_recommendation", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("approved_paise", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("member_explanation", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("current_action", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "processing_fixtures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="processing_fixtures_claim_version_uq",
        ),
    )
    op.create_index(
        "ix_processing_fixtures_claim_id",
        "processing_fixtures",
        ["claim_id"],
    )
    op.create_table(
        "casefiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["member_version_id"],
            ["member_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="casefiles_claim_version_uq",
        ),
    )
    op.create_index("ix_casefiles_claim_id", "casefiles", ["claim_id"])
    op.create_table(
        "decision_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("casefile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("approved_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "approved_paise >= 0",
            name="decision_records_approved_nonnegative",
        ),
        sa.ForeignKeyConstraint(["casefile_id"], ["casefiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_hash",
            name="decision_records_canonical_hash_uq",
        ),
        sa.UniqueConstraint(
            "claim_id",
            "claim_version",
            name="decision_records_claim_version_uq",
        ),
    )
    op.create_index("ix_decision_records_claim_id", "decision_records", ["claim_id"])
    op.create_table(
        "rule_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("policy_path", sa.String(length=255), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("amount_before_paise", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_paise", sa.BigInteger(), nullable=False),
        sa.Column("amount_after_paise", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_record_id"],
            ["decision_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_record_id",
            "sequence",
            name="rule_results_decision_sequence_uq",
        ),
    )
    op.create_index(
        "ix_rule_results_decision_record_id",
        "rule_results",
        ["decision_record_id"],
    )


def downgrade() -> None:
    op.drop_table("rule_results")
    op.drop_table("decision_records")
    op.drop_table("casefiles")
    op.drop_table("processing_fixtures")
    for column_name in (
        "current_action",
        "member_explanation",
        "approved_paise",
        "adjudication_recommendation",
    ):
        op.drop_column("claims", column_name)
