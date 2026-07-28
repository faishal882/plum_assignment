"""Add the EMP008 local development identity.

Revision ID: 20260728_0026
Revises: 20260728_0025
Create Date: 2026-07-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0026"
down_revision: str | None = "20260728_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBER_ID = "00000000-0000-0000-0000-000000000008"


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
                "id": _MEMBER_ID,
                "username": "member.emp008",
                "normalized_username": "member.emp008",
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
    op.bulk_insert(
        links,
        [{"user_id": _MEMBER_ID, "member_id": "EMP008"}],
    )


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
