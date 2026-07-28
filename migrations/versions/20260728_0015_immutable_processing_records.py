"""Enforce immutable processing evidence and trace records.

Revision ID: 20260728_0015
Revises: 20260728_0014
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0015"
down_revision: str | None = "20260728_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "processing_fixtures",
    "casefiles",
    "decision_records",
    "rule_results",
    "document_triage_results",
    "member_actions",
)


def upgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
            """
        )


def downgrade() -> None:
    for table_name in reversed(IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
