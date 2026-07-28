import asyncio
import json
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pypdf import PdfWriter
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimActionRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    DocumentRow,
    DocumentVersionRow,
)


@pytest.mark.asyncio
async def test_replacement_preserves_versions_and_records_a_complete_trace(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]
        replaced = await _replace(client, claim_id, "trace-replacement")

    async with app.state.session_factory() as session:
        claim_versions = (
            await session.scalars(
                select(ClaimVersionRow)
                .where(ClaimVersionRow.claim_id == claim_id)
                .order_by(ClaimVersionRow.version)
            )
        ).all()
        document = await session.scalar(select(DocumentRow).where(DocumentRow.claim_id == claim_id))
        document_versions = (
            await session.scalars(
                select(DocumentVersionRow)
                .join(DocumentRow)
                .where(DocumentRow.claim_id == claim_id)
                .order_by(DocumentVersionRow.version)
            )
        ).all()
        action = await session.scalar(
            select(ClaimActionRow).where(ClaimActionRow.claim_id == claim_id)
        )
        event = await session.scalar(
            select(AuditEventRow).where(
                AuditEventRow.claim_id == claim_id,
                AuditEventRow.event_type == "DOCUMENT_REPLACED",
            )
        )
        work = (
            await session.scalars(
                select(ClaimWorkItemRow)
                .where(ClaimWorkItemRow.claim_id == claim_id)
                .order_by(ClaimWorkItemRow.created_at)
            )
        ).all()

    assert replaced.status_code == 200
    assert [row.version for row in claim_versions] == [1, 2]
    assert document is not None
    assert [row.version for row in document_versions] == [1, 2]
    assert document_versions[0].sha256 != document_versions[1].sha256
    assert all((tmp_path / row.relative_path).is_file() for row in document_versions)
    assert claim_versions[0].submission["source"] == "SUBMISSION"
    assert claim_versions[1].submission["source"] == "DOCUMENT_REPLACEMENT"
    assert claim_versions[0].submission["claimed_paise"] == 150_000
    assert claim_versions[1].submission["claimed_paise"] == 150_000
    assert claim_versions[0].submission["documents"][0]["document_version"] == 1
    assert claim_versions[1].submission["documents"][0]["document_version"] == 2
    assert claim_versions[0].submission["documents"][0]["document_version_id"] == str(
        document_versions[0].id
    )
    assert claim_versions[1].submission["documents"][0]["document_version_id"] == str(
        document_versions[1].id
    )
    assert action is not None
    assert action.previous_version == 1
    assert action.result_version == 2
    assert action.replacement_document_id == document.id
    assert action.replacement_document_version_id == document_versions[1].id
    assert event is not None
    assert event.actor_user_id == action.scope_user_id
    assert event.payload == {
        "action_id": str(action.id),
        "previous_claim_version": 1,
        "new_claim_version": 2,
        "previous_lifecycle_status": "QUEUED",
        "new_lifecycle_status": "QUEUED",
        "client_document_id": "doc-prescription",
        "document_id": str(document.id),
        "document_version_id": str(document_versions[1].id),
        "previous_document_version": 1,
        "new_document_version": 2,
        "sha256": document_versions[1].sha256,
    }
    assert [item.status for item in work] == ["SUPERSEDED", "AVAILABLE"]
    assert work[1].operation_key == f"claim:{claim_id}:process:v2"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_identical_actions_return_one_result(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]

    async def replace_once() -> Response:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await _replace(client, claim_id, "concurrent-identical")

    responses = await asyncio.gather(*(replace_once() for _ in range(5)))

    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["action_id"] for response in responses}) == 1
    async with app.state.session_factory() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(table))
            for table in (ClaimActionRow, DocumentRow, DocumentVersionRow, ClaimWorkItemRow)
        ]
    assert counts == [1, 1, 2, 2]
    assert len(_stored_files(tmp_path)) == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_distinct_actions_apply_only_one_expected_version(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]

    async def replace_once(key: str, width: int) -> Response:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await _replace(client, claim_id, key, width=width)

    responses = await asyncio.gather(
        replace_once("concurrent-first", 120),
        replace_once("concurrent-second", 130),
    )

    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "STALE_CLAIM_VERSION"
    assert conflict.json()["error"]["current_version"] == 2
    async with app.state.session_factory() as session:
        claim = await session.get(ClaimRow, claim_id)
        action_count = await session.scalar(select(func.count()).select_from(ClaimActionRow))
    assert claim is not None
    assert claim.current_version == 2
    assert action_count == 1
    assert len(_stored_files(tmp_path)) == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_action_authorization_and_lifecycle_fail_without_artifacts(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]
        other_member = await _replace(
            client,
            claim_id,
            "other-member-action",
            username="member.emp002",
        )
        reviewer = await _replace(
            client,
            claim_id,
            "reviewer-action",
            username="reviewer.local",
        )
        async with app.state.session_factory.begin() as session:
            await session.execute(
                update(ClaimRow).where(ClaimRow.id == claim_id).values(lifecycle_status="DECIDED")
            )
        invalid_lifecycle = await _replace(client, claim_id, "decided-action")

    assert other_member.status_code == 404
    assert other_member.json()["error"]["code"] == "CLAIM_NOT_FOUND"
    assert reviewer.status_code == 403
    assert reviewer.json()["error"]["code"] == "CLAIM_ACTION_FORBIDDEN"
    assert invalid_lifecycle.status_code == 409
    assert invalid_lifecycle.json()["error"]["code"] == "CLAIM_ACTION_NOT_ALLOWED"
    assert len(_stored_files(tmp_path)) == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_replacement_resumes_an_action_required_claim(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]
        async with app.state.session_factory.begin() as session:
            await session.execute(
                update(ClaimRow)
                .where(ClaimRow.id == claim_id)
                .values(lifecycle_status="ACTION_REQUIRED")
            )
        response = await _replace(client, claim_id, "resume-action-required")

    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "QUEUED"
    async with app.state.session_factory() as session:
        claim = await session.get(ClaimRow, claim_id)
    assert claim is not None
    assert claim.lifecycle_status == "QUEUED"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_failed_action_rolls_back_key_versions_work_and_artifact(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit(client)).json()["claim_id"]

        async with app.state.engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE FUNCTION reject_replacement_work_item() RETURNS trigger AS $$
                    BEGIN
                        IF right(NEW.operation_key, 2) = 'v2' THEN
                            RAISE EXCEPTION 'injected replacement failure'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TRIGGER reject_replacement_work_item_insert
                    BEFORE INSERT ON claim_work_items
                    FOR EACH ROW EXECUTE FUNCTION reject_replacement_work_item()
                    """
                )
            )

        try:
            with pytest.raises(IntegrityError):
                await _replace(client, claim_id, "rollback-action")
        finally:
            async with app.state.engine.begin() as connection:
                await connection.execute(
                    text("DROP TRIGGER reject_replacement_work_item_insert ON claim_work_items")
                )
                await connection.execute(text("DROP FUNCTION reject_replacement_work_item()"))

        async with app.state.session_factory() as session:
            claim = await session.get(ClaimRow, claim_id)
            counts = [
                await session.scalar(select(func.count()).select_from(table))
                for table in (
                    ClaimActionRow,
                    ClaimVersionRow,
                    DocumentVersionRow,
                    AuditEventRow,
                    ClaimWorkItemRow,
                )
            ]
            work_status = await session.scalar(select(ClaimWorkItemRow.status))

        assert claim is not None
        assert claim.current_version == 1
        assert counts == [0, 1, 1, 2, 1]
        assert work_status == "AVAILABLE"
        assert len(_stored_files(tmp_path)) == 1

        retried = await _replace(client, claim_id, "rollback-action")

    assert retried.status_code == 200
    assert retried.json()["version"] == 2
    await app.state.engine.dispose()


async def _submit(client: AsyncClient) -> Response:
    return await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp001",
            "Idempotency-Key": "claim-for-action-integration",
        },
        data={"metadata": json.dumps(_metadata())},
        files={"files": ("prescription.pdf", _pdf_bytes(), "application/pdf")},
    )


async def _replace(
    client: AsyncClient,
    claim_id: str,
    key: str,
    *,
    width: int = 120,
    username: str = "member.emp001",
) -> Response:
    return await client.post(
        f"/v1/claims/{claim_id}/actions",
        headers={"X-Dev-Username": username, "Idempotency-Key": key},
        data={
            "command": json.dumps(
                {
                    "type": "REPLACE_DOCUMENT",
                    "expected_version": 1,
                    "client_document_id": "doc-prescription",
                }
            )
        },
        files={"file": ("replacement.pdf", _pdf_bytes(width), "application/pdf")},
    )


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }


def _pdf_bytes(width: int = 100) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _stored_files(data_root) -> list:
    return [path for path in (data_root / "objects").rglob("*") if path.is_file()]
