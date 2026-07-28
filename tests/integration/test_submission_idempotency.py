import asyncio
import json
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pypdf import PdfWriter
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.models import (
    ClaimRow,
    ClaimWorkItemRow,
    DocumentRow,
    DocumentVersionRow,
    IdempotencyKeyRow,
)


@pytest.mark.asyncio
async def test_sequential_retry_returns_original_receipt_without_duplicate_state(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _submit(client, "member.emp001", "sequential-retry")
        replay = await _submit(client, "member.emp001", "sequential-retry")

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert await _counts(app) == [1, 1, 1, 1, 1]
    assert len(_stored_files(tmp_path)) == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_part", ["metadata", "manifest", "content"])
async def test_key_reuse_with_a_different_canonical_request_conflicts(
    migrated_database_url: str,
    tmp_path,
    changed_part: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    changed_metadata = _metadata()
    content = _pdf_bytes()
    if changed_part == "metadata":
        changed_metadata["claimed_amount"] = "1501.00"
    elif changed_part == "manifest":
        changed_metadata["documents"] = [
            {"upload_index": 0, "client_document_id": "different-document"}
        ]
    else:
        content = _pdf_bytes(width=101)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await _submit(client, "member.emp001", "conflicting-reuse")
        conflict = await _submit(
            client,
            "member.emp001",
            "conflicting-reuse",
            metadata=changed_metadata,
            content=content,
        )

    assert accepted.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _counts(app) == [1, 1, 1, 1, 1]
    assert len(_stored_files(tmp_path)) == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_identical_submissions_collapse_to_one_acceptance(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)

    async def submit_once() -> Response:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await _submit(client, "member.emp001", "concurrent-retry")

    responses = await asyncio.gather(*(submit_once() for _ in range(5)))

    assert {response.status_code for response in responses} == {202}
    assert len({response.json()["claim_id"] for response in responses}) == 1
    assert await _counts(app) == [1, 1, 1, 1, 1]
    assert len(_stored_files(tmp_path)) == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_same_key_is_independent_for_each_member(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    member_two_metadata = _metadata()
    member_two_metadata["member_id"] = "EMP002"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _submit(client, "member.emp001", "member-scoped-key")
        second = await _submit(
            client,
            "member.emp002",
            "member-scoped-key",
            metadata=member_two_metadata,
        )

    assert first.status_code == second.status_code == 202
    assert first.json()["claim_id"] != second.json()["claim_id"]
    assert await _counts(app) == [2, 2, 2, 2, 2]
    await app.state.engine.dispose()


async def _submit(
    client: AsyncClient,
    username: str,
    idempotency_key: str,
    *,
    metadata: dict[str, object] | None = None,
    content: bytes | None = None,
) -> Response:
    return await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": username,
            "Idempotency-Key": idempotency_key,
        },
        data={"metadata": json.dumps(metadata or _metadata())},
        files={
            "files": (
                "prescription.pdf",
                content or _pdf_bytes(),
                "application/pdf",
            )
        },
    )


async def _counts(app) -> list[int]:
    async with app.state.session_factory() as session:
        return [
            int(await session.scalar(select(func.count()).select_from(table)) or 0)
            for table in (
                ClaimRow,
                ClaimWorkItemRow,
                DocumentRow,
                DocumentVersionRow,
                IdempotencyKeyRow,
            )
        ]


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
