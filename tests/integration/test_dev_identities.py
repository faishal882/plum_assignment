from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.identity import PostgresIdentityProvider
from claims_backend.infrastructure.postgres.models import MemberRow, MemberVersionRow, UserRow
from claims_backend.runtime.profiles import ExecutionProfile


@pytest.mark.asyncio
async def test_dev_identity_directory_lists_seeded_members_and_reviewers(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/dev/identities")

    assert response.status_code == 200
    identities = response.json()
    assert any(
        identity["username"] == "member.emp001"
        and identity["member_id"] == "EMP001"
        and "MEMBER" in identity["roles"]
        for identity in identities
    )
    assert any(
        identity["username"] == "reviewer.local" and "REVIEWER" in identity["roles"]
        for identity in identities
    )
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_dev_identity_creator_mints_claim_ready_member_identity(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    suffix = uuid4().hex[:8]
    username = f"demo.{suffix}"
    member_id = f"DEMO-{suffix.upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/dev/identities",
            json={
                "username": username.upper(),
                "full_name": "Demo Person",
                "member_id": member_id,
                "date_of_birth": "1990-01-02",
                "gender": "FEMALE",
                "join_date": "2024-01-01",
            },
        )
        listed = await client.get("/v1/dev/identities")

    assert created.status_code == 201
    assert created.json() == {
        "username": username,
        "display_name": "Demo Person",
        "member_id": member_id,
        "roles": ["MEMBER"],
    }
    assert any(identity["username"] == username for identity in listed.json())

    async with app.state.session_factory() as session:
        user = await session.scalar(select(UserRow).where(UserRow.normalized_username == username))
        member = await session.scalar(
            select(MemberRow).where(
                MemberRow.policy_id == "PLUM_GHI_2024",
                MemberRow.external_member_id == member_id,
            )
        )
        version = (
            None
            if member is None
            else await session.scalar(
                select(MemberVersionRow).where(MemberVersionRow.member_id == member.id)
            )
        )
        principal = await PostgresIdentityProvider(session).resolve(username)
    assert user is not None
    assert member is not None
    assert version is not None
    assert version.name == "Demo Person"
    assert principal is not None
    assert principal.member_id == member_id
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_dev_identity_creator_rejects_duplicates(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    suffix = uuid4().hex[:8]
    payload = {
        "username": f"demo.duplicate.{suffix}",
        "full_name": "Demo Duplicate",
        "member_id": f"DEMO-DUPLICATE-{suffix.upper()}",
        "date_of_birth": "1990-01-02",
        "gender": "FEMALE",
        "join_date": "2024-01-01",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/dev/identities", json=payload)
        duplicate_username = await client.post("/v1/dev/identities", json=payload)
        duplicate_member = await client.post(
            "/v1/dev/identities", json={**payload, "username": f"demo.duplicate2.{suffix}"}
        )

    assert created.status_code == 201
    assert duplicate_username.status_code == 409
    assert duplicate_username.json()["error"]["code"] == "USERNAME_ALREADY_EXISTS"
    assert duplicate_member.status_code == 409
    assert duplicate_member.json()["error"]["code"] == "MEMBER_ID_ALREADY_EXISTS"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_dev_identity_directory_is_local_only(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(
        Settings(
            database_url=migrated_database_url,
            data_root=tmp_path,
            execution_profile=ExecutionProfile.LIVE_INTELLIGENCE,
            run_live_aws=True,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/dev/identities")

    assert response.status_code == 404
    await app.state.engine.dispose()
