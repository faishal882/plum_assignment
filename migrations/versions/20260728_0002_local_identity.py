"""Add local development identities and claim ownership.

Revision ID: 20260728_0002
Revises: 20260728_0001
Create Date: 2026-07-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0002"
down_revision: str | None = "20260728_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBER_EMP001_ID = "00000000-0000-0000-0000-000000000001"
_MEMBER_EMP002_ID = "00000000-0000-0000-0000-000000000002"
_REVIEWER_ID = "00000000-0000-0000-0000-000000000101"
_OPERATOR_ID = "00000000-0000-0000-0000-000000000102"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("normalized_username", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "normalized_username = lower(btrim(username))",
            name="users_username_normalized",
        ),
        sa.CheckConstraint(
            "normalized_username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
            name="users_username_supported_characters",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_username"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_table(
        "user_member_links",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("member_id"),
    )

    timestamp = datetime(2026, 7, 28, tzinfo=UTC)
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
                "id": _MEMBER_EMP001_ID,
                "username": "member.emp001",
                "normalized_username": "member.emp001",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            {
                "id": _MEMBER_EMP002_ID,
                "username": "member.emp002",
                "normalized_username": "member.emp002",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            {
                "id": _REVIEWER_ID,
                "username": "reviewer.local",
                "normalized_username": "reviewer.local",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            {
                "id": _OPERATOR_ID,
                "username": "operator.local",
                "normalized_username": "operator.local",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ],
    )
    user_roles = sa.table(
        "user_roles",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()),
    )
    op.bulk_insert(
        user_roles,
        [
            {"user_id": _MEMBER_EMP001_ID, "role": "MEMBER"},
            {"user_id": _MEMBER_EMP002_ID, "role": "MEMBER"},
            {"user_id": _REVIEWER_ID, "role": "REVIEWER"},
            {"user_id": _OPERATOR_ID, "role": "OPERATOR"},
        ],
    )
    member_links = sa.table(
        "user_member_links",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("member_id", sa.String()),
    )
    op.bulk_insert(
        member_links,
        [
            {"user_id": _MEMBER_EMP001_ID, "member_id": "EMP001"},
            {"user_id": _MEMBER_EMP002_ID, "member_id": "EMP002"},
        ],
    )

    op.add_column(
        "claims",
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("owner_username_snapshot", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE claims SET owner_user_id = CAST(:user_id AS uuid), "
            "owner_username_snapshot = 'member.emp001'"
        ).bindparams(user_id=_MEMBER_EMP001_ID)
    )
    op.alter_column("claims", "owner_user_id", nullable=False)
    op.alter_column("claims", "owner_username_snapshot", nullable=False)
    op.create_foreign_key(
        "claims_owner_user_id_fkey",
        "claims",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_claims_owner_user_id", "claims", ["owner_user_id"], unique=False)

    op.add_column(
        "audit_events",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "audit_events",
        sa.Column("actor_username_snapshot", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE audit_events SET actor_user_id = CAST(:user_id AS uuid), "
            "actor_username_snapshot = 'member.emp001'"
        ).bindparams(user_id=_MEMBER_EMP001_ID)
    )
    op.alter_column("audit_events", "actor_user_id", nullable=False)
    op.alter_column("audit_events", "actor_username_snapshot", nullable=False)
    op.create_foreign_key(
        "audit_events_actor_user_id_fkey",
        "audit_events",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("audit_events_actor_user_id_fkey", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "actor_username_snapshot")
    op.drop_column("audit_events", "actor_user_id")
    op.drop_index("ix_claims_owner_user_id", table_name="claims")
    op.drop_constraint("claims_owner_user_id_fkey", "claims", type_="foreignkey")
    op.drop_column("claims", "owner_username_snapshot")
    op.drop_column("claims", "owner_user_id")
    op.drop_table("user_member_links")
    op.drop_table("user_roles")
    op.drop_table("users")
