"""Preserve Textract expense semantic labels with each OCR observation.

Revision ID: 20260729_0034
Revises: 20260729_0033
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0034"
down_revision: str | None = "20260729_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ocr_observations",
        sa.Column("field_type", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ocr_observations", "field_type")
