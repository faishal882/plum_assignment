import json
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import PageArtifactApplication, SourceDocument
from claims_backend.config import Settings
from claims_backend.infrastructure.page_artifacts import LocalPageArtifactStore
from claims_backend.infrastructure.page_renderer import LocalPageRenderer
from claims_backend.infrastructure.postgres.models import (
    DocumentPageArtifactRow,
    DocumentRow,
    DocumentVersionRow,
)
from claims_backend.infrastructure.postgres.page_artifacts import (
    PostgresPageArtifactRepository,
)


@pytest.mark.asyncio
async def test_rendered_pages_are_persisted_once_in_stable_order(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "page-artifacts",
            },
            data={"metadata": json.dumps(_metadata())},
            files={"files": ("two-pages.pdf", _two_page_pdf(), "application/pdf")},
        )
    assert submitted.status_code == 202

    async with app.state.session_factory() as session:
        document = (await session.scalars(select(DocumentRow))).one()
        version = (await session.scalars(select(DocumentVersionRow))).one()
    source = SourceDocument(
        document_id=document.id,
        document_version_id=version.id,
        relative_path=version.relative_path,
        media_type=version.media_type,
        sha256=version.sha256,
        page_count=version.page_count,
    )
    application = PageArtifactApplication(
        LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
        LocalPageArtifactStore(tmp_path),
        PostgresPageArtifactRepository(app.state.session_factory),
    )

    first = await application.process(source)
    replay = await application.process(source)

    assert [artifact.page_number for artifact in first] == [1, 2]
    assert replay == first
    assert all(artifact.document_version_id == version.id for artifact in first)
    assert all((tmp_path / artifact.relative_path).is_file() for artifact in first)
    async with app.state.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(DocumentPageArtifactRow))
    assert count == 2
    await app.state.engine.dispose()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "F-PDF"}],
    }


def _two_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=400, height=300)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
