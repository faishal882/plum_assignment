"""Add the EMP003 and EMP007 local development identities.

Revision ID: 20260728_0023
Revises: 20260728_0022
Create Date: 2026-07-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0023"
down_revision: str | None = "20260728_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBERS = (
    ("00000000-0000-0000-0000-000000000003", "member.emp003", "EMP003"),
    ("00000000-0000-0000-0000-000000000007", "member.emp007", "EMP007"),
)


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
                "id": user_id,
                "username": username,
                "normalized_username": username,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            for user_id, username, _ in _MEMBERS
        ],
    )
    user_roles = sa.table(
        "user_roles",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("role", sa.String()),
    )
    op.bulk_insert(
        user_roles,
        [{"user_id": user_id, "role": "MEMBER"} for user_id, _, _ in _MEMBERS],
    )
    member_links = sa.table(
        "user_member_links",
        sa.column("user_id", postgresql.UUID(as_uuid=True)),
        sa.column("member_id", sa.String()),
    )
    op.bulk_insert(
        member_links,
        [{"user_id": user_id, "member_id": member_id} for user_id, _, member_id in _MEMBERS],
    )


def downgrade() -> None:
    for user_id, _, _ in reversed(_MEMBERS):
        op.execute(
            sa.text(
                "DELETE FROM user_member_links WHERE user_id = CAST(:user_id AS uuid)"
            ).bindparams(user_id=user_id)
        )
        op.execute(
            sa.text("DELETE FROM user_roles WHERE user_id = CAST(:user_id AS uuid)").bindparams(
                user_id=user_id
            )
        )
        op.execute(
            sa.text("DELETE FROM users WHERE id = CAST(:user_id AS uuid)").bindparams(
                user_id=user_id
            )
        )
