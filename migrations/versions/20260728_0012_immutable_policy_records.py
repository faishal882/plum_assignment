"""Enforce immutable compiled policy records.

Revision ID: 20260728_0012
Revises: 20260728_0011
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260728_0012"
down_revision: str | None = "20260728_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_policy_version_content_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'policy_versions records cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                OLD.policy_id,
                OLD.version,
                OLD.policy_source_id,
                OLD.policy_overlay_id,
                OLD.compiler_version,
                OLD.ir,
                OLD.ir_sha256,
                OLD.compiled_at
            ) IS DISTINCT FROM ROW(
                NEW.policy_id,
                NEW.version,
                NEW.policy_source_id,
                NEW.policy_overlay_id,
                NEW.compiler_version,
                NEW.ir,
                NEW.ir_sha256,
                NEW.compiled_at
            ) THEN
                RAISE EXCEPTION 'compiled policy content is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER policy_versions_content_immutable
        BEFORE UPDATE OR DELETE ON policy_versions
        FOR EACH ROW EXECUTE FUNCTION reject_policy_version_content_mutation()
        """
    )
    for table_name in ("policy_findings", "policy_activation_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_setup_source_mutation()
            """
        )


def downgrade() -> None:
    for table_name in ("policy_activation_events", "policy_findings"):
        op.execute(f"DROP TRIGGER {table_name}_immutable ON {table_name}")
    op.execute(
        "DROP TRIGGER policy_versions_content_immutable ON policy_versions"
    )
    op.execute("DROP FUNCTION reject_policy_version_content_mutation()")
