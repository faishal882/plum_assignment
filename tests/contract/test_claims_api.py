import json
from datetime import date
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from claims_backend.api.app import create_app
from claims_backend.api.dependencies import get_identity_provider
from claims_backend.application.identity import IdentityProvider
from claims_backend.config import Settings
from claims_backend.domain.identity import Principal, Role


class FixedIdentityProvider(IdentityProvider):
    async def resolve(self, username: str) -> Principal | None:
        return Principal(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            username="external-subject",
            roles=frozenset({Role.MEMBER}),
            member_id="EMP001",
        )


def fixed_identity_provider() -> IdentityProvider:
    return FixedIdentityProvider()


def pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_identity_provider_can_be_replaced_without_changing_claim_routes(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    app.dependency_overrides[get_identity_provider] = fixed_identity_provider
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "external-subject"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )

    assert response.status_code == 202
    assert response.json()["lifecycle_status"] == "QUEUED"

    app.dependency_overrides.clear()
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_claim_submission_requires_a_local_identity(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "IDENTITY_REQUIRED",
            "message": "A local development identity is required.",
            "details": [],
        }
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_malformed_local_identity_is_rejected_before_lookup(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/v1/claims/{uuid4()}",
            headers={"X-Dev-Username": "../../EMP001"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "MALFORMED_IDENTITY",
            "message": "The local development identity is malformed.",
            "details": [],
        }
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_unknown_local_identity_is_rejected(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "unknown.user"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_IDENTITY",
            "message": "The local development identity is not recognized.",
            "details": [],
        }
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_member_can_submit_and_retrieve_a_queued_claim(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
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
            headers={"X-Dev-Username": "MEMBER.EMP001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )

        assert submitted.status_code == 202
        receipt = submitted.json()
        assert receipt["version"] == 1
        assert receipt["lifecycle_status"] == "QUEUED"
        assert receipt["status_url"] == f"/v1/claims/{receipt['claim_id']}"

        retrieved = await client.get(
            receipt["status_url"],
            headers={"X-Dev-Username": "member.emp001"},
        )

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
async def test_another_member_cannot_discover_a_claim(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )
        response = await client.get(
            submitted.json()["status_url"],
            headers={"X-Dev-Username": "member.emp002"},
        )

    assert submitted.status_code == 202
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CLAIM_NOT_FOUND"

    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username",
    ["member.emp002", "reviewer.local", "operator.local"],
)
async def test_non_owner_cannot_submit_for_member(
    migrated_database_url: str,
    username: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "doc-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": username},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "CLAIM_SUBMISSION_FORBIDDEN",
            "message": "The identity cannot submit a claim for this member.",
            "details": [],
        }
    }

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_unknown_claim_returns_a_stable_not_found_error(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/v1/claims/{uuid4()}",
            headers={"X-Dev-Username": "member.emp001"},
        )

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
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
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
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(invalid_metadata)},
            files={"files": ("prescription.pdf", pdf_bytes(), "application/pdf")},
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
