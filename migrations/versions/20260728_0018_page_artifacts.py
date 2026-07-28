"""Add immutable rendered page artifacts.

Revision ID: 20260728_0018
Revises: 20260728_0017
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0018"
down_revision: str | None = "20260728_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_page_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("original_sha256", sa.String(length=64), nullable=False),
        sa.Column("rendered_sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("render_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number > 0", name="page_artifacts_page_positive"),
        sa.CheckConstraint("size_bytes > 0", name="page_artifacts_size_positive"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "page_number",
            "render_version",
            name="document_page_artifacts_version_page_render_uq",
        ),
        sa.UniqueConstraint(
            "relative_path",
            name="document_page_artifacts_relative_path_uq",
        ),
    )
    op.create_index(
        "ix_document_page_artifacts_document_version_id",
        "document_page_artifacts",
        ["document_version_id"],
    )
    op.execute(
        """
        CREATE TRIGGER document_page_artifacts_immutable
        BEFORE UPDATE OR DELETE ON document_page_artifacts
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER document_page_artifacts_immutable ON document_page_artifacts")
    op.drop_table("document_page_artifacts")
