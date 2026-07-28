"""Cache immutable OCR results per document role.

Revision ID: 20260729_0032
Revises: 20260729_0031
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0032"
down_revision: str | None = "20260729_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TRIGGER ocr_page_results_immutable ON ocr_page_results")
    op.add_column(
        "ocr_page_results",
        sa.Column("document_role", sa.String(length=32), nullable=True),
    )
    op.execute("UPDATE ocr_page_results SET document_role = 'UNKNOWN'")
    op.alter_column("ocr_page_results", "document_role", nullable=False)
    op.drop_constraint(
        "ocr_page_results_artifact_provider_uq",
        "ocr_page_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "ocr_page_results_artifact_provider_uq",
        "ocr_page_results",
        ["page_artifact_id", "provider_name", "provider_version", "document_role"],
    )
    op.execute(
        """
        CREATE TRIGGER ocr_page_results_immutable
        BEFORE UPDATE OR DELETE ON ocr_page_results
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER ocr_page_results_immutable ON ocr_page_results")
    op.drop_constraint(
        "ocr_page_results_artifact_provider_uq",
        "ocr_page_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "ocr_page_results_artifact_provider_uq",
        "ocr_page_results",
        ["page_artifact_id", "provider_name", "provider_version"],
    )
    op.drop_column("ocr_page_results", "document_role")
    op.execute(
        """
        CREATE TRIGGER ocr_page_results_immutable
        BEFORE UPDATE OR DELETE ON ocr_page_results
        FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
        """
    )
