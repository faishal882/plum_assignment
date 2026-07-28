from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.claims import ClaimsApplication
from claims_backend.application.identity import IdentityProvider
from claims_backend.domain.identity import InvalidUsernameError, Principal
from claims_backend.infrastructure.postgres.identity import PostgresIdentityProvider
from claims_backend.infrastructure.postgres.repositories import PostgresClaimsRepository


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_identity_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_claims_application(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ClaimsApplication:
    return ClaimsApplication(PostgresClaimsRepository(session))


ClaimsApplicationDependency = Annotated[ClaimsApplication, Depends(get_claims_application)]


def get_identity_provider(
    session: Annotated[AsyncSession, Depends(get_identity_session)],
) -> IdentityProvider:
    return PostgresIdentityProvider(session)


async def get_current_principal(
    provider: Annotated[IdentityProvider, Depends(get_identity_provider)],
    username: Annotated[str | None, Header(alias="X-Dev-Username")] = None,
) -> Principal:
    if username is None or not username.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "IDENTITY_REQUIRED",
                "message": "A local development identity is required.",
                "details": [],
            },
        )
    try:
        principal = await provider.resolve(username)
    except InvalidUsernameError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MALFORMED_IDENTITY",
                "message": "The local development identity is malformed.",
                "details": [],
            },
        ) from error
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_IDENTITY",
                "message": "The local development identity is not recognized.",
                "details": [],
            },
        )
    return principal


CurrentPrincipalDependency = Annotated[Principal, Depends(get_current_principal)]
