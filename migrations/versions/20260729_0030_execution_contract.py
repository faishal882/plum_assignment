"""Persist immutable workflow execution contracts.

Revision ID: 20260729_0030
Revises: 20260729_0029
Create Date: 2026-07-29
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0030"
down_revision: str | None = "20260729_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNSPECIFIED = {
    "schema_version": "execution-contract-v1",
    "execution_profile": "UNSPECIFIED",
    "ocr_provider": {"name": "UNSPECIFIED", "version": "UNSPECIFIED"},
    "model_provider": {"name": "UNSPECIFIED", "version": "UNSPECIFIED"},
    "model_routes": [],
}


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("execution_contract", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.get_bind().execute(
        sa.text("UPDATE workflow_runs SET execution_contract = CAST(:contract AS jsonb)"),
        {"contract": json.dumps(_UNSPECIFIED, sort_keys=True)},
    )
    op.alter_column("workflow_runs", "execution_contract", nullable=False)


def downgrade() -> None:
    op.drop_column("workflow_runs", "execution_contract")
