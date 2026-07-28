import json
from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from claims_backend.api.app import create_app
from claims_backend.config import Settings


@pytest.mark.asyncio
async def test_member_can_submit_and_retrieve_a_queued_claim(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url))
    transport = ASGITransport(app=app)

    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": date(2024, 11, 1).isoformat(),
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", b"%PDF-1.4 placeholder", "application/pdf")},
        )

        assert submitted.status_code == 202
        receipt = submitted.json()
        assert receipt["version"] == 1
        assert receipt["lifecycle_status"] == "QUEUED"
        assert receipt["status_url"] == f"/v1/claims/{receipt['claim_id']}"

        retrieved = await client.get(receipt["status_url"])

    assert retrieved.status_code == 200
    assert retrieved.json() == {
        "claim_id": receipt["claim_id"],
        "version": 1,
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "lifecycle_status": "QUEUED",
        "progress": {
            "current_stage": "QUEUED",
            "is_terminal": False,
        },
        "created_at": retrieved.json()["created_at"],
        "updated_at": retrieved.json()["updated_at"],
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_unknown_claim_returns_a_stable_not_found_error(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/claims/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "CLAIM_NOT_FOUND",
            "message": "Claim was not found.",
            "details": [],
        }
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_invalid_claim_metadata_returns_a_stable_error(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url))
    transport = ASGITransport(app=app)
    invalid_metadata = {
        "member_id": "EMP001",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "-1.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            data={"metadata": json.dumps(invalid_metadata)},
            files={"files": ("prescription.pdf", b"%PDF-1.4 placeholder", "application/pdf")},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_CLAIM_METADATA"
    assert body["error"]["message"] == "Claim metadata is invalid."
    assert {detail["location"][0] for detail in body["error"]["details"]} == {
        "policy_id",
        "claimed_amount",
    }

    await app.state.engine.dispose()
