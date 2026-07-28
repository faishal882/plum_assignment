"""Add the EMP009 local development identity.

Revision ID: 20260728_0022
Revises: 20260728_0021
Create Date: 2026-07-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0022"
down_revision: str | None = "20260728_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBER_EMP009_ID = "00000000-0000-0000-0000-000000000009"


def upgrade() -> None:
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
                "id": _MEMBER_EMP009_ID,
                "username": "member.emp009",
                "normalized_username": "member.emp009",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        ],
    )
    user_roles = sa.table(
        "user_roles",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()),
    )
    op.bulk_insert(
        user_roles,
        [{"user_id": _MEMBER_EMP009_ID, "role": "MEMBER"}],
    )
    member_links = sa.table(
        "user_member_links",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("member_id", sa.String()),
    )
    op.bulk_insert(
        member_links,
        [{"user_id": _MEMBER_EMP009_ID, "member_id": "EMP009"}],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM user_member_links WHERE user_id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_EMP009_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM user_roles WHERE user_id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_EMP009_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM users WHERE id = CAST(:user_id AS uuid)").bindparams(
            user_id=_MEMBER_EMP009_ID
        )
    )
