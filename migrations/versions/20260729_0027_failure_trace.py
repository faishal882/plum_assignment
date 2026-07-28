"""Add component failure traces and the EMP006 local identity.

Revision ID: 20260729_0027
Revises: 20260728_0026
Create Date: 2026-07-29
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0027"
down_revision: str | None = "20260728_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBER_ID = "00000000-0000-0000-0000-000000000006"


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("processing_quality", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "component_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False),
        sa.Column("decision_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("criticality", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("effect_on_handling", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts > 0", name="component_failures_attempts_positive"),
        sa.CheckConstraint(
            "completeness >= 0 AND completeness <= 1",
            name="component_failures_completeness_ratio",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="component_failures_confidence_ratio",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["decision_record_id"],
            ["decision_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_record_id",
            "component",
            name="component_failures_decision_component_uq",
        ),
    )
    op.create_index(
        "ix_component_failures_claim_id",
        "component_failures",
        ["claim_id"],
    )
    op.create_index(
        "ix_component_failures_decision_record_id",
        "component_failures",
        ["decision_record_id"],
    )
    _add_local_identity()


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_member_links WHERE user_id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM user_roles WHERE user_id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM users WHERE id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_ID
        )
    )
    op.drop_index("ix_component_failures_decision_record_id", table_name="component_failures")
    op.drop_index("ix_component_failures_claim_id", table_name="component_failures")
    op.drop_table("component_failures")
    op.drop_column("claims", "processing_quality")


def _add_local_identity() -> None:
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
    users = sa.table(
        "users",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("username", sa.String()),
        sa.column("normalized_username", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        users,
        [
            {
                "id": _MEMBER_ID,
                "username": "member.emp006",
                "normalized_username": "member.emp006",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )
    roles = sa.table(
        "user_roles",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()),
    )
    op.bulk_insert(roles, [{"user_id": _MEMBER_ID, "role": "MEMBER"}])
    links = sa.table(
        "user_member_links",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("member_id", sa.String()),
    )
    op.bulk_insert(links, [{"user_id": _MEMBER_ID, "member_id": "EMP006"}])
