from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.application.identity import IdentityProvider
from claims_backend.domain.identity import Principal, Role, normalize_username
from claims_backend.infrastructure.postgres.models import (
    UserMemberLinkRow,
    UserRoleRow,
    UserRow,
)


class PostgresIdentityProvider(IdentityProvider):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, username: str) -> Principal | None:
        normalized = normalize_username(username)
        user = await self._session.scalar(
            select(UserRow).where(UserRow.normalized_username == normalized)
        )
        if user is None:
            return None

        role_values = (
            (
                await self._session.scalars(
                    select(UserRoleRow.role).where(UserRoleRow.user_id == user.id)
                )
            )
            .unique()
            .all()
        )
        member_id = await self._session.scalar(
            select(UserMemberLinkRow.member_id).where(UserMemberLinkRow.user_id == user.id)
        )
        return Principal(
            user_id=user.id,
            username=user.username,
            roles=frozenset(Role(role) for role in role_values),
            member_id=member_id,
        )
