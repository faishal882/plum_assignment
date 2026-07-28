"""Add immutable page OCR results and observations.

Revision ID: 20260728_0019
Revises: 20260728_0018
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0019"
down_revision: str | None = "20260728_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ocr_page_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_version", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("provider_request_id", sa.String(length=128), nullable=False),
        sa.Column("retry_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number > 0", name="ocr_page_results_page_positive"),
        sa.CheckConstraint(
            "retry_attempts >= 0",
            name="ocr_page_results_retry_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["page_artifact_id"],
            ["document_page_artifacts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "page_artifact_id",
            "provider_name",
            "provider_version",
            name="ocr_page_results_artifact_provider_uq",
        ),
    )
    op.create_index(
        "ix_ocr_page_results_document_version_id",
        "ocr_page_results",
        ["document_version_id"],
    )
    op.create_table(
        "ocr_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ocr_page_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("region", postgresql.JSONB(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number > 0", name="ocr_observations_page_positive"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ocr_observations_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["ocr_page_result_id"],
            ["ocr_page_results.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            name="ocr_observations_observation_id_uq",
        ),
    )
    op.create_index(
        "ix_ocr_observations_document_version_id",
        "ocr_observations",
        ["document_version_id"],
    )
    for table_name in ("ocr_page_results", "ocr_observations"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
            """
        )


def downgrade() -> None:
    for table_name in ("ocr_observations", "ocr_page_results"):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.drop_table("ocr_observations")
    op.drop_table("ocr_page_results")
