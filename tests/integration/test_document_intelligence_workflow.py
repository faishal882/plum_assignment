import json
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import (
    OcrApplication,
    PageArtifactApplication,
    RenderedPage,
)
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    TextractProfile,
)
from claims_backend.infrastructure.fixtures.recorded_model import (
    RecordedStructuredModelTransport,
)
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.page_artifacts import (
    LocalPageArtifactReader,
    LocalPageArtifactStore,
)
from claims_backend.infrastructure.page_renderer import LocalPageRenderer
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    DocumentPageArtifactRow,
    ModelExtractionRow,
    OcrObservationRow,
    OcrPageResultRow,
)
from claims_backend.infrastructure.postgres.ocr import PostgresOcrRepository
from claims_backend.infrastructure.postgres.page_artifacts import (
    PostgresPageArtifactRepository,
)
from claims_backend.infrastructure.postgres.structured_model import (
    PostgresStructuredModelRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.model.application import StructuredModelApplication
from claims_backend.model.routing import ModelRouter


class WorkflowRecordedOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "workflow-recorded-v1"

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        observation_id = sha256(
            f"{page.document_version_id}:{page.page_number}:{role.value}".encode()
        ).hexdigest()
        return OcrPageResult(
            profile=(
                TextractProfile.EXPENSE
                if role is DocumentRole.HOSPITAL_BILL
                else TextractProfile.FORMS_TABLES
            ),
            provider_request_id=f"recorded-{page.document_version_id}-{page.page_number}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=page.page_number,
                    kind=OcrObservationKind.LINE,
                    text=f"{role.value} page {page.page_number}",
                    confidence=0.99,
                    region=NormalizedRegion(
                        x=0.1,
                        y=0.1,
                        width=0.3,
                        height=0.1,
                    ),
                    source_id=f"line-{page.page_number}",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_recorded_workflow_renders_and_ocr_processes_every_page(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    prescription = _prescription()
    bill = _two_page_pdf()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "document-intelligence-workflow",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
                ("files", ("hospital-bill.pdf", bill, "application/pdf")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(
            app.state.session_factory
        ).seed_document_intelligence_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(bill).hexdigest(),
        )

    page_repository = PostgresPageArtifactRepository(app.state.session_factory)
    ocr_repository = PostgresOcrRepository(app.state.session_factory)
    recorded_model = RecordedStructuredModelTransport(
        {
            ModelRoute.COMPLEX_EXTRACTION: {
                "schema_version": "complex-extraction-v1",
                "candidates": [],
            }
        }
    )
    workflows = PostgresWorkflowRepository(app.state.session_factory)
    processor = PostgresClaimProcessor(
        app.state.session_factory,
        page_artifacts=PageArtifactApplication(
            LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
            LocalPageArtifactStore(tmp_path),
            page_repository,
        ),
        page_repository=page_repository,
        ocr=OcrApplication(
            LocalPageArtifactReader(tmp_path),
            WorkflowRecordedOcr(),
            ocr_repository,
        ),
        ocr_repository=ocr_repository,
        structured_model=StructuredModelApplication(
            ModelRouter.default(
                region="us-west-2",
                model_id="qwen.qwen3-235b-a22b-2507-v1:0",
            ),
            recorded_model,
            PostgresStructuredModelRepository(app.state.session_factory),
        ),
    )
    runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        workflows,
        processor=processor,
    )
    await runtime.setup()
    assert await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
        "document-intelligence-worker",
        ClaimWorkflowProcessor(workflows, runtime).process,
    )

    async with app.state.session_factory() as session:
        pages = await session.scalar(select(func.count()).select_from(DocumentPageArtifactRow))
        results = await session.scalar(select(func.count()).select_from(OcrPageResultRow))
        observations = await session.scalar(select(func.count()).select_from(OcrObservationRow))
        extractions = await session.scalar(select(func.count()).select_from(ModelExtractionRow))
    assert pages == 3
    assert results == 3
    assert observations == 3
    assert extractions == 2
    assert recorded_model.calls == [
        ModelRoute.COMPLEX_EXTRACTION,
        ModelRoute.COMPLEX_EXTRACTION,
    ]

    workflow_run = await workflows.get_by_work_item(await _work_item_id(app))
    assert workflow_run is not None
    effects = await workflows.list_effects(workflow_run.id)
    assert [effect.effect_type for effect in effects] == [
        "CLAIM_VERSION_LOADED",
        "LOCAL_MEDIA_INSPECTED",
        "DOCUMENT_TRIAGE_COMPLETED",
        "DOCUMENT_PAGES_RENDERED",
        "PAGE_OCR_COMPLETED",
        "STRUCTURED_EXTRACTION_COMPLETED",
        "WORKFLOW_SKELETON_COMPLETED",
    ]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_oversize_rendered_page_requests_a_smaller_document_without_ocr(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    prescription = _prescription()
    bill = _two_page_pdf()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "oversize-rendered-page",
            },
            data={"metadata": json.dumps(_oversize_metadata())},
            files=[
                ("files", ("hospital-bill.pdf", bill, "application/pdf")),
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(
            app.state.session_factory
        ).seed_document_intelligence_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(bill).hexdigest(),
        )

        page_repository = PostgresPageArtifactRepository(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=PostgresClaimProcessor(
                app.state.session_factory,
                page_artifacts=PageArtifactApplication(
                    LocalPageRenderer(tmp_path, max_page_bytes=10),
                    LocalPageArtifactStore(tmp_path),
                    page_repository,
                ),
                page_repository=page_repository,
                ocr=OcrApplication(
                    LocalPageArtifactReader(tmp_path),
                    WorkflowRecordedOcr(),
                    PostgresOcrRepository(app.state.session_factory),
                ),
            ),
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
            "oversize-page-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert projection.status_code == 200
    assert projection.json()["lifecycle_status"] == "ACTION_REQUIRED"
    assert projection.json()["action"] == {
        "code": "PAGE_TOO_LARGE_FOR_OCR",
        "message": (
            "Page 1 of the hospital bill (F102) is too large for OCR. "
            "Please replace it with a clearer or smaller document."
        ),
        "observed_document_roles": ["PRESCRIPTION", "HOSPITAL_BILL"],
        "required_document_roles": ["HOSPITAL_BILL"],
        "affected_documents": [
            {
                "client_document_id": "F102",
                "observed_role": "HOSPITAL_BILL",
                "requested_action": "REPLACE",
            }
        ],
    }
    async with app.state.session_factory() as session:
        result_count = await session.scalar(select(func.count()).select_from(OcrPageResultRow))
    assert result_count == 0
    workflow_run = await workflows.get_by_work_item(await _work_item_id(app))
    assert workflow_run is not None
    effects = await workflows.list_effects(workflow_run.id)
    assert [effect.effect_type for effect in effects] == [
        "CLAIM_VERSION_LOADED",
        "LOCAL_MEDIA_INSPECTED",
        "DOCUMENT_TRIAGE_COMPLETED",
        "DOCUMENT_RENDERING_BLOCKED",
        "MEMBER_ACTION_COMMITTED",
    ]
    await app.state.engine.dispose()


async def _work_item_id(app) -> UUID:
    from claims_backend.infrastructure.postgres.models import ClaimWorkItemRow

    async with app.state.session_factory() as session:
        return (await session.scalars(select(ClaimWorkItemRow.id))).one()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F101"},
            {"upload_index": 1, "client_document_id": "F102"},
        ],
    }


def _oversize_metadata() -> dict[str, object]:
    metadata = _metadata()
    metadata["documents"] = [
        {"upload_index": 0, "client_document_id": "F102"},
        {"upload_index": 1, "client_document_id": "F101"},
    ]
    return metadata


def _prescription() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), "PRESCRIPTION", fill="black")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def _two_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=400, height=300)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
