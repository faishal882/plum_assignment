import json
from hashlib import sha256
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import (
    OcrApplication,
    PageArtifactApplication,
    RenderedPage,
    SourceDocument,
)
from claims_backend.config import Settings
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    TextractProfile,
)
from claims_backend.infrastructure.page_artifacts import (
    LocalPageArtifactReader,
    LocalPageArtifactStore,
)
from claims_backend.infrastructure.page_renderer import LocalPageRenderer
from claims_backend.infrastructure.postgres.models import (
    DocumentRow,
    DocumentVersionRow,
    OcrObservationRow,
    OcrPageResultRow,
)
from claims_backend.infrastructure.postgres.ocr import PostgresOcrRepository
from claims_backend.infrastructure.postgres.page_artifacts import (
    PostgresPageArtifactRepository,
)


class RecordedOcrProvider:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "recorded-v1"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        self.calls.append(page.page_number)
        observation_id = sha256(
            f"{page.document_version_id}:{page.page_number}:{role.value}".encode()
        ).hexdigest()
        return OcrPageResult(
            profile=TextractProfile.TEXT,
            provider_request_id=f"recorded-{page.page_number}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=page.page_number,
                    kind=OcrObservationKind.LINE,
                    text=f"Page {page.page_number}",
                    confidence=0.99,
                    region=NormalizedRegion(
                        x=0.1,
                        y=0.1,
                        width=0.2,
                        height=0.1,
                    ),
                    source_id=f"line-{page.page_number}",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_page_ocr_is_idempotent_and_merges_in_page_order(
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
                "Idempotency-Key": "ocr-persistence",
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
    pages = await PageArtifactApplication(
        LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
        LocalPageArtifactStore(tmp_path),
        PostgresPageArtifactRepository(app.state.session_factory),
    ).process(source)
    provider = RecordedOcrProvider()
    ocr = OcrApplication(
        LocalPageArtifactReader(tmp_path),
        provider,
        PostgresOcrRepository(app.state.session_factory),
    )

    first = await ocr.process(pages, DocumentRole.UNKNOWN)
    replay = await ocr.process(pages, DocumentRole.UNKNOWN)
    role_aware = await ocr.process(pages, DocumentRole.HOSPITAL_BILL)

    assert provider.calls == [1, 2, 1, 2]
    assert [item.page_number for item in first] == [1, 2]
    assert [item.text for item in first] == ["Page 1", "Page 2"]
    assert replay == first
    assert [item.page_number for item in role_aware] == [1, 2]
    assert {item.observation_id for item in first}.isdisjoint(
        item.observation_id for item in role_aware
    )
    async with app.state.session_factory() as session:
        result_count = await session.scalar(select(func.count()).select_from(OcrPageResultRow))
        observation_count = await session.scalar(
            select(func.count()).select_from(OcrObservationRow)
        )
    assert result_count == 4
    assert observation_count == 4
    await app.state.engine.dispose()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "F-OCR"}],
    }


def _two_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=400, height=300)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
