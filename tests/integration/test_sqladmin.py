from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.models import (
    UserMemberLinkRow,
    UserRoleRow,
    UserRow,
)

_ADMIN_USERNAME = "claims-admin"
_ADMIN_PASSWORD = "correct-horse-battery-staple"
_ADMIN_SECRET = "sqladmin-test-secret-with-32-characters"


@pytest.mark.asyncio
async def test_sqladmin_is_disabled_by_default(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/", follow_redirects=False)

    assert app.state.sqladmin is None
    assert response.status_code == 404
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_sqladmin_requires_login_and_lists_identity_views_after_authentication(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(
        Settings(
            database_url=migrated_database_url,
            data_root=tmp_path,
            sqladmin_enabled=True,
            sqladmin_username=_ADMIN_USERNAME,
            sqladmin_password=_ADMIN_PASSWORD,
            sqladmin_secret_key=_ADMIN_SECRET,
        )
    )
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        protected = await client.get("/admin/", follow_redirects=False)
        rejected = await client.post(
            "/admin/login",
            data={"username": _ADMIN_USERNAME, "password": "incorrect-password"},
            follow_redirects=False,
        )
        accepted = await client.post(
            "/admin/login",
            data={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
            follow_redirects=False,
        )
        dashboard = await client.get("/admin/", follow_redirects=False)
        users = await client.get("/admin/user-row/list", follow_redirects=False)
        claims = await client.get("/admin/claim-row/list", follow_redirects=False)
        ocr_observations = await client.get(
            "/admin/ocr-observation-row/list", follow_redirects=False
        )
        decision_records = await client.get(
            "/admin/decision-record-row/list", follow_redirects=False
        )
        workflow_runs = await client.get("/admin/workflow-run-row/list", follow_redirects=False)
        policy_versions = await client.get("/admin/policy-version-row/list", follow_redirects=False)
        logged_out = await client.get("/admin/logout", follow_redirects=False)
        protected_again = await client.get("/admin/", follow_redirects=False)

    assert protected.status_code == 302
    assert protected.headers["location"] == "http://test/admin/login"
    assert rejected.status_code == 400
    assert accepted.status_code == 302
    assert accepted.headers["location"] == "http://test/admin/"
    assert dashboard.status_code == 200
    assert "Users" in dashboard.text
    assert "User Roles" in dashboard.text
    assert "Member Links" in dashboard.text
    assert "Policy Members" in dashboard.text
    assert "Claims" in dashboard.text
    assert "OCR Observations" in dashboard.text
    assert "Decision Records" in dashboard.text
    assert "Workflow Runs" in dashboard.text
    assert "Policy Versions" in dashboard.text
    assert users.status_code == 200
    assert claims.status_code == 200
    assert ocr_observations.status_code == 200
    assert decision_records.status_code == 200
    assert workflow_runs.status_code == 200
    assert policy_versions.status_code == 200
    assert "member.emp001" in users.text
    assert logged_out.status_code == 302
    assert protected_again.status_code == 302
    assert protected_again.headers["location"] == "http://test/admin/login"

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_sqladmin_creates_a_normalized_user_with_role_and_member_link(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(
        Settings(
            database_url=migrated_database_url,
            data_root=tmp_path,
            sqladmin_enabled=True,
            sqladmin_username=_ADMIN_USERNAME,
            sqladmin_password=_ADMIN_PASSWORD,
            sqladmin_secret_key=_ADMIN_SECRET,
        )
    )
    transport = ASGITransport(app=app)
    suffix = uuid4().hex[:12]
    submitted_username = f"ADMIN.TEST.{suffix.upper()}"
    normalized_username = submitted_username.casefold()
    member_id = f"ADMIN_TEST_{suffix.upper()}"
    created_user_id = None

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/admin/login",
                data={"username": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
            )
            created = await client.post(
                "/admin/user-row/create",
                data={"username": submitted_username},
                follow_redirects=False,
            )
            assert created.status_code == 302

            async with app.state.runtime.session_factory() as session:
                user = await session.scalar(
                    select(UserRow).where(UserRow.normalized_username == normalized_username)
                )
            assert user is not None
            created_user_id = user.id
            assert user.username == normalized_username
            assert user.created_at is not None
            assert user.updated_at is not None

            role_created = await client.post(
                "/admin/user-role-row/create",
                data={"user_id": str(user.id), "role": "REVIEWER"},
                follow_redirects=False,
            )
            link_created = await client.post(
                "/admin/user-member-link-row/create",
                data={"user_id": str(user.id), "member_id": member_id},
                follow_redirects=False,
            )
            assert role_created.status_code == 302
            assert link_created.status_code == 302

            async with app.state.runtime.session_factory() as session:
                role = await session.scalar(
                    select(UserRoleRow).where(
                        UserRoleRow.user_id == user.id,
                        UserRoleRow.role == "REVIEWER",
                    )
                )
                member_link = await session.scalar(
                    select(UserMemberLinkRow).where(
                        UserMemberLinkRow.user_id == user.id,
                        UserMemberLinkRow.member_id == member_id,
                    )
                )
            assert role is not None
            assert member_link is not None
    finally:
        if created_user_id is not None:
            async with app.state.runtime.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        delete(UserMemberLinkRow).where(
                            UserMemberLinkRow.user_id == created_user_id
                        )
                    )
                    await session.execute(
                        delete(UserRoleRow).where(UserRoleRow.user_id == created_user_id)
                    )
                    await session.execute(delete(UserRow).where(UserRow.id == created_user_id))
        await app.state.engine.dispose()
