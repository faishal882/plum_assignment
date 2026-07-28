from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.domain.identity import Role
from claims_backend.infrastructure.postgres.identity import PostgresIdentityProvider
from claims_backend.infrastructure.postgres.models import UserRow


@pytest.mark.asyncio
async def test_seeded_identities_resolve_case_insensitively_with_roles(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        provider = PostgresIdentityProvider(session)
        member = await provider.resolve("  MEMBER.EMP001  ")
        reviewer = await provider.resolve("reviewer.local")
        operator = await provider.resolve("operator.local")

    assert member is not None
    assert member.user_id == UUID("00000000-0000-0000-0000-000000000001")
    assert member.username == "member.emp001"
    assert member.member_id == "EMP001"
    assert member.roles == frozenset({Role.MEMBER})

    assert reviewer is not None
    assert reviewer.member_id is None
    assert reviewer.roles == frozenset({Role.REVIEWER})

    assert operator is not None
    assert operator.member_id is None
    assert operator.roles == frozenset({Role.OPERATOR})

    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_a_case_variant_of_an_existing_username(
    migrated_database_url: str,
) -> None:
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    UserRow(
                        id=uuid4(),
                        username="Member.EMP001",
                        normalized_username="member.emp001",
                        created_at=now,
                        updated_at=now,
                    )
                )

    await engine.dispose()
