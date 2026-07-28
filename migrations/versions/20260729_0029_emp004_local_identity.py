"""Add the EMP004 local development identity.

Revision ID: 20260729_0029
Revises: 20260729_0028
Create Date: 2026-07-29
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0029"
down_revision: str | None = "20260729_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBER_ID = "00000000-0000-0000-0000-000000000004"


def upgrade() -> None:
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
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
                "username": "member.emp004",
                "normalized_username": "member.emp004",
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
    op.bulk_insert(links, [{"user_id": _MEMBER_ID, "member_id": "EMP004"}])


def downgrade() -> None:
    for table_name in ("user_member_links", "user_roles", "users"):
        op.execute(
            sa.text(
                f"DELETE FROM {table_name} WHERE "
                f"{'user_id' if table_name != 'users' else 'id'} = "
                "CAST(:user_id AS uuid)"
            ).bindparams(user_id=_MEMBER_ID)
        )
