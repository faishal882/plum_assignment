import json
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from claims_backend.api.app import create_app
from claims_backend.config import Settings


@pytest.mark.asyncio
async def test_member_can_replace_a_document_with_a_versioned_action(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await _submit_claim(client)
        claim_id = submitted.json()["claim_id"]
        replaced = await _replace_document(
            client,
            claim_id,
            "replace-prescription-v1",
        )
        current = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert replaced.status_code == 200
    body = replaced.json()
    assert body == {
        "action_id": body["action_id"],
        "action_type": "REPLACE_DOCUMENT",
        "claim_id": claim_id,
        "previous_version": 1,
        "version": 2,
        "lifecycle_status": "QUEUED",
        "document": {
            "client_document_id": "doc-prescription",
            "version": 2,
        },
        "status_url": f"/v1/claims/{claim_id}",
    }
    assert current.status_code == 200
    assert current.json()["version"] == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_identical_action_retry_returns_the_original_result(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        first = await _replace_document(client, claim_id, "repeat-action")
        replay = await _replace_document(client, claim_id, "repeat-action")

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["version"] == 2
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_old_action_replay_keeps_its_original_receipt_after_later_actions(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        first = await _replace_document(client, claim_id, "first-action")
        second = await _replace_document(
            client,
            claim_id,
            "second-action",
            expected_version=2,
            width=130,
        )
        replay = await _replace_document(client, claim_id, "first-action")

    assert first.status_code == second.status_code == replay.status_code == 200
    assert second.json()["version"] == 3
    assert replay.json() == first.json()
    assert replay.json()["version"] == 2
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 3
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_action_key_reuse_with_different_content_conflicts(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        accepted = await _replace_document(client, claim_id, "conflicting-action")
        conflict = await _replace_document(
            client,
            claim_id,
            "conflicting-action",
            width=130,
        )

    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ACTION_IDEMPOTENCY_KEY_REUSED"
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_stale_action_returns_current_version_without_mutating_claim(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        accepted = await _replace_document(client, claim_id, "accepted-action")
        stale = await _replace_document(client, claim_id, "stale-action", width=140)
        current = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert accepted.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_CLAIM_VERSION"
    assert stale.json()["error"]["current_version"] == 2
    assert current.json()["version"] == 2
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_action_requires_a_key_and_expected_version(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        missing_key = await client.post(
            f"/v1/claims/{claim_id}/actions",
            headers={"X-Dev-Username": "member.emp001"},
            data={
                "command": json.dumps(
                    {
                        "type": "REPLACE_DOCUMENT",
                        "expected_version": 1,
                        "client_document_id": "doc-prescription",
                    }
                )
            },
            files={"file": ("replacement.pdf", _pdf_bytes(120), "application/pdf")},
        )
        missing_version = await client.post(
            f"/v1/claims/{claim_id}/actions",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "missing-expected-version",
            },
            data={
                "command": json.dumps(
                    {
                        "type": "REPLACE_DOCUMENT",
                        "client_document_id": "doc-prescription",
                    }
                )
            },
            files={"file": ("replacement.pdf", _pdf_bytes(120), "application/pdf")},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert missing_version.status_code == 422
    assert missing_version.json()["error"]["code"] == "INVALID_CLAIM_ACTION"
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_replacement_requires_an_existing_claim_document(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = (await _submit_claim(client)).json()["claim_id"]
        response = await _replace_document(
            client,
            claim_id,
            "unknown-document",
            client_document_id="missing-document",
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_DOCUMENT_NOT_FOUND"
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 1
    await app.state.engine.dispose()


async def _replace_document(
    client: AsyncClient,
    claim_id: str,
    idempotency_key: str,
    *,
    expected_version: int = 1,
    client_document_id: str = "doc-prescription",
    width: int = 120,
    username: str = "member.emp001",
):
    return await client.post(
        f"/v1/claims/{claim_id}/actions",
        headers={
            "X-Dev-Username": username,
            "Idempotency-Key": idempotency_key,
        },
        data={
            "command": json.dumps(
                {
                    "type": "REPLACE_DOCUMENT",
                    "expected_version": expected_version,
                    "client_document_id": client_document_id,
                }
            )
        },
        files={
            "file": (
                "corrected-prescription.pdf",
                _pdf_bytes(width=width),
                "application/pdf",
            )
        },
    )


async def _submit_claim(client: AsyncClient):
    return await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp001",
            "Idempotency-Key": "claim-for-replacement",
        },
        data={
            "metadata": json.dumps(
                {
                    "member_id": "EMP001",
                    "policy_id": "PLUM_GHI_2024",
                    "claim_category": "CONSULTATION",
                    "treatment_date": "2024-11-01",
                    "claimed_amount": "1500.00",
                    "currency": "INR",
                    "documents": [
                        {
                            "upload_index": 0,
                            "client_document_id": "doc-prescription",
                        }
                    ],
                }
            )
        },
        files={
            "files": (
                "prescription.pdf",
                _pdf_bytes(),
                "application/pdf",
            )
        },
    )


def _pdf_bytes(width: int = 100) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
