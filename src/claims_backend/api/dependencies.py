from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.claims import ClaimsApplication
from claims_backend.infrastructure.postgres.repositories import PostgresClaimsRepository


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_claims_application(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimsApplication:
    return ClaimsApplication(PostgresClaimsRepository(session))


ClaimsApplicationDependency = Annotated[ClaimsApplication, Depends(get_claims_application)]
