"""Add immutable policy and member data imports.

Revision ID: 20260728_0008
Revises: 20260728_0007
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0008"
down_revision: str | None = "20260728_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(source_bytes) > 0",
            name="policy_sources_bytes_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_sha256"),
    )
    op.create_index("ix_policy_sources_policy_id", "policy_sources", ["policy_id"])
    op.create_table(
        "setup_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("policy_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_data_source_name", sa.String(length=255), nullable=True),
        sa.Column("member_data_sha256", sa.String(length=64), nullable=True),
        sa.Column("member_data_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(member_data_bytes IS NULL) = (member_data_sha256 IS NULL)",
            name="setup_imports_member_data_hash_pair",
        ),
        sa.CheckConstraint(
            "(member_data_bytes IS NULL) = (member_data_source_name IS NULL)",
            name="setup_imports_member_data_name_pair",
        ),
        sa.ForeignKeyConstraint(
            ["policy_source_id"],
            ["policy_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_sha256"),
    )
    op.create_index("ix_setup_imports_policy_id", "setup_imports", ["policy_id"])
    op.create_table(
        "members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("external_member_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "external_member_id",
            name="members_policy_external_id_uq",
        ),
    )
    op.create_index("ix_members_policy_id", "members", ["policy_id"])
    op.create_table(
        "member_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("setup_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("gender", sa.String(length=32), nullable=False),
        sa.Column("relationship", sa.String(length=32), nullable=False),
        sa.Column("join_date", sa.Date(), nullable=True),
        sa.Column("dependent_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_pointer", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="member_versions_version_positive"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["primary_member_id"],
            ["members.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["setup_import_id"],
            ["setup_imports.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "member_id",
            "version",
            name="member_versions_member_version_uq",
        ),
    )
    op.create_index("ix_member_versions_member_id", "member_versions", ["member_id"])
    op.create_index(
        "ix_member_versions_setup_import_id",
        "member_versions",
        ["setup_import_id"],
    )
    op.create_table(
        "import_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setup_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("source_pointer", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["setup_import_id"],
            ["setup_imports.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_findings_setup_import_id",
        "import_findings",
        ["setup_import_id"],
    )
    op.create_table(
        "member_claim_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setup_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("history_claim_id", sa.String(length=128), nullable=False),
        sa.Column("treatment_date", sa.Date(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=True),
        sa.Column("source_pointer", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_paise >= 0",
            name="member_claim_history_amount_nonnegative",
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["setup_import_id"],
            ["setup_imports.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "setup_import_id",
            "history_claim_id",
            name="member_claim_history_import_claim_uq",
        ),
    )
    op.create_index(
        "ix_member_claim_history_member_id",
        "member_claim_history",
        ["member_id"],
    )
    op.create_index(
        "ix_member_claim_history_setup_import_id",
        "member_claim_history",
        ["setup_import_id"],
    )
    op.create_table(
        "member_utilization_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setup_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("used_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source_pointer", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "period_end >= period_start",
            name="member_utilization_snapshots_period_ordered",
        ),
        sa.CheckConstraint(
            "used_paise >= 0",
            name="member_utilization_snapshots_used_nonnegative",
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["setup_import_id"],
            ["setup_imports.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "setup_import_id",
            "member_id",
            "period_start",
            "period_end",
            name="member_utilization_snapshots_import_member_period_uq",
        ),
    )
    op.create_index(
        "ix_member_utilization_snapshots_member_id",
        "member_utilization_snapshots",
        ["member_id"],
    )
    op.create_index(
        "ix_member_utilization_snapshots_setup_import_id",
        "member_utilization_snapshots",
        ["setup_import_id"],
    )


def downgrade() -> None:
    op.drop_table("member_utilization_snapshots")
    op.drop_table("member_claim_history")
    op.drop_table("import_findings")
    op.drop_table("member_versions")
    op.drop_table("members")
    op.drop_table("setup_imports")
    op.drop_table("policy_sources")
