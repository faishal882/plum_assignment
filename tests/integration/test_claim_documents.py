import json
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.models import (
    ClaimRow,
    ClaimWorkItemRow,
    DocumentRow,
    DocumentVersionRow,
)


@pytest.mark.asyncio
async def test_claim_acceptance_persists_and_seals_document_versions(
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
        "documents": [{"upload_index": 0, "client_document_id": "client-prescription"}],
    }
    pdf = _pdf_bytes()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("../../prescription.txt", pdf, "text/plain")},
        )

    assert response.status_code == 202

    async with app.state.session_factory() as session:
        document = await session.scalar(select(DocumentRow))
        version = await session.scalar(select(DocumentVersionRow))

    assert document is not None
    assert document.client_document_id == "client-prescription"
    assert document.upload_index == 0
    assert version is not None
    assert version.document_id == document.id
    assert version.original_filename == "prescription.txt"
    assert version.media_type == "application/pdf"
    assert version.size_bytes == len(pdf)
    assert version.page_count == 1
    assert (tmp_path / version.relative_path).read_bytes() == pdf

    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type", "format_kind", "stored_media_type"),
    [
        ("claim.pdf", "application/pdf", "PDF", "application/pdf"),
        ("claim.jpeg", "image/jpeg", "JPEG", "image/jpeg"),
        ("claim.png", "image/png", "PNG", "image/png"),
    ],
)
async def test_api_accepts_each_supported_document_format(
    migrated_database_url: str,
    tmp_path,
    filename: str,
    content_type: str,
    format_kind: str,
    stored_media_type: str,
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
        "documents": [{"upload_index": 0, "client_document_id": "client-document"}],
    }
    document_bytes = _pdf_bytes() if format_kind == "PDF" else _image_bytes(format_kind)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": (filename, document_bytes, content_type)},
        )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        version = await session.scalar(select(DocumentVersionRow))
    assert version is not None
    assert version.media_type == stored_media_type

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_manifest_upload_indexes_control_document_mapping(
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
        "documents": [
            {"upload_index": 1, "client_document_id": "client-image"},
            {"upload_index": 0, "client_document_id": "client-pdf"},
        ],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files=[
                ("files", ("first.pdf", _pdf_bytes(), "application/pdf")),
                ("files", ("second.png", _png_bytes(), "image/png")),
            ],
        )

    assert response.status_code == 202

    async with app.state.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(
                        DocumentRow.upload_index,
                        DocumentRow.client_document_id,
                        DocumentVersionRow.media_type,
                    )
                    .join(DocumentVersionRow)
                    .order_by(DocumentRow.upload_index)
                )
            )
            .tuples()
            .all()
        )

    assert rows == [
        (0, "client-pdf", "application/pdf"),
        (1, "client-image", "image/png"),
    ]

    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_status", "expected_code"),
    [
        ("unsupported", 415, "UNSUPPORTED_DOCUMENT"),
        ("corrupt", 422, "CORRUPT_DOCUMENT"),
        ("encrypted", 422, "ENCRYPTED_DOCUMENT"),
        ("too_many_pages", 422, "DOCUMENT_PAGE_LIMIT_EXCEEDED"),
    ],
)
async def test_invalid_document_creates_no_claim_or_artifact(
    migrated_database_url: str,
    tmp_path,
    case: str,
    expected_status: int,
    expected_code: str,
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
        "documents": [{"upload_index": 0, "client_document_id": "client-prescription"}],
    }
    content = {
        "unsupported": b"plain text is not a supported document",
        "corrupt": b"%PDF- structurally broken",
        "encrypted": _pdf_bytes(password="secret"),
        "too_many_pages": _pdf_bytes(page_count=11),
    }[case]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("uploaded.data", content, "application/octet-stream")},
        )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert response.json()["error"]["details"][0]["location"] == ["files", 0]

    async with app.state.session_factory() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(table))
            for table in (ClaimRow, ClaimWorkItemRow, DocumentRow, DocumentVersionRow)
        ]

    assert counts == [0, 0, 0, 0]
    assert list((tmp_path / ".staging").iterdir()) == []
    assert [path for path in (tmp_path / "objects").rglob("*") if path.is_file()] == []

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_api_enforces_configured_per_file_limit(
    migrated_database_url: str,
    tmp_path,
) -> None:
    pdf = _pdf_bytes()
    app = create_app(
        Settings(
            database_url=migrated_database_url,
            data_root=tmp_path,
            max_file_bytes=len(pdf) - 1,
        )
    )
    transport = ASGITransport(app=app)
    metadata = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "client-prescription"}],
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/claims",
            headers={"X-Dev-Username": "member.emp001"},
            data={"metadata": json.dumps(metadata)},
            files={"files": ("prescription.pdf", pdf, "application/pdf")},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "DOCUMENT_TOO_LARGE"
    assert list((tmp_path / ".staging").iterdir()) == []

    await app.state.engine.dispose()


def _pdf_bytes(page_count: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _png_bytes() -> bytes:
    return _image_bytes("PNG")


def _image_bytes(format_name: str) -> bytes:
    image = Image.new("RGB", (16, 16), color="white")
    output = BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()
