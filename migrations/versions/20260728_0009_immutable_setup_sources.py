"""Enforce immutable setup source records.

Revision ID: 20260728_0009
Revises: 20260728_0008
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0009"
down_revision: str | None = "20260728_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_setup_source_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% records are immutable', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in ("policy_sources", "setup_imports"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
            """
        )


def downgrade() -> None:
    for table_name in ("setup_imports", "policy_sources"):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION reject_setup_source_mutation()")
