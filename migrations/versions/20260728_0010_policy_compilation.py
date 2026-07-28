"""Add policy overlays, compiled versions, and findings.

Revision ID: 20260728_0010
Revises: 20260728_0009
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0010"
down_revision: str | None = "20260728_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_overlays",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("overlay_id", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("base_policy_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(source_bytes) > 0",
            name="policy_overlays_bytes_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "overlay_id",
            "version",
            name="policy_overlays_identity_version_uq",
        ),
        sa.UniqueConstraint("source_sha256"),
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_overlay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compiler_version", sa.String(length=64), nullable=False),
        sa.Column("ir", postgresql.JSONB(), nullable=True),
        sa.Column("ir_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint("version > 0", name="policy_versions_version_positive"),
        sa.CheckConstraint(
            "status IN ('INVALID', 'COMPILED', 'ACTIVE', 'RETIRED')",
            name="policy_versions_status_supported",
        ),
        sa.ForeignKeyConstraint(
            ["policy_overlay_id"],
            ["policy_overlays.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_source_id"],
            ["policy_sources.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "version",
            name="policy_versions_policy_version_uq",
        ),
        sa.UniqueConstraint(
            "policy_source_id",
            "policy_overlay_id",
            "compiler_version",
            name="policy_versions_compilation_identity_uq",
        ),
    )
    op.create_index("ix_policy_versions_policy_id", "policy_versions", ["policy_id"])
    op.create_index(
        "policy_versions_one_active_uq",
        "policy_versions",
        ["policy_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "policy_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("source_pointer", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved_by_overlay", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_findings_policy_version_id",
        "policy_findings",
        ["policy_version_id"],
    )
    op.create_table(
        "policy_activation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_activation_events_policy_version_id",
        "policy_activation_events",
        ["policy_version_id"],
    )
    op.execute(
        """
        CREATE TRIGGER policy_overlays_immutable
        BEFORE UPDATE OR DELETE ON policy_overlays
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER policy_overlays_immutable ON policy_overlays")
    op.drop_table("policy_activation_events")
    op.drop_table("policy_findings")
    op.drop_index("policy_versions_one_active_uq", table_name="policy_versions")
    op.drop_index("ix_policy_versions_policy_id", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_table("policy_overlays")
