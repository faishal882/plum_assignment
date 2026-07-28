"""Add immutable structured model extractions.

Revision ID: 20260728_0020
Revises: 20260728_0019
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0020"
down_revision: str | None = "20260728_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_request_id", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name="model_extractions_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="model_extractions_latency_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "route",
            "model_id",
            "prompt_version",
            "schema_version",
            "input_sha256",
            name="model_extractions_replay_uq",
        ),
    )
    op.create_index(
        "ix_model_extractions_document_version_id",
        "model_extractions",
        ["document_version_id"],
    )
    op.create_table(
        "evidence_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("fact_path", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("normalized_value", postgresql.JSONB(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("producer", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="evidence_candidates_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["model_extraction_id"],
            ["model_extractions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            name="evidence_candidates_candidate_id_uq",
        ),
    )
    op.create_index(
        "ix_evidence_candidates_model_extraction_id",
        "evidence_candidates",
        ["model_extraction_id"],
    )
    for table_name in ("model_extractions", "evidence_candidates"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
            """
        )


def downgrade() -> None:
    for table_name in ("evidence_candidates", "model_extractions"):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.drop_table("evidence_candidates")
    op.drop_table("model_extractions")
