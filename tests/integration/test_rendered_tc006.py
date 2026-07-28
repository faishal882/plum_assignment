import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import OcrApplication, PageArtifactApplication
from claims_backend.application.setup_import import SetupDataApplication
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
from claims_backend.infrastructure.postgres.models import DocumentRow, DocumentVersionRow
from claims_backend.infrastructure.postgres.ocr import PostgresOcrRepository
from claims_backend.infrastructure.postgres.page_artifacts import (
    PostgresPageArtifactRepository,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
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

_POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()


class Tc006RecordedOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "tc006-rendered-v1"

    def analyze(self, page, role: DocumentRole) -> OcrPageResult:
        observation_id = _observation_id(page.document_version_id)
        return OcrPageResult(
            profile=TextractProfile.EXPENSE,
            provider_request_id=f"tc006-{page.document_version_id}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=1,
                    kind=OcrObservationKind.EXPENSE_FIELD,
                    text=(
                        "Priya Singh Root Canal Treatment 8000 "
                        "Teeth Whitening 4000 Total 12000"
                    ),
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.3),
                    source_id="recorded-expense-1",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_rendered_tc006_partially_approves_only_covered_dental_item(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_utilization(factory)
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    bill = _document_image(
        "DENTAL BILL\nPatient: Priya Singh\n"
        "Root Canal Treatment 8000\nTeeth Whitening 4000\nTotal 12000"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp002",
                "Idempotency-Key": "tc006-rendered",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[("files", ("dental-bill.jpg", bill, "image/jpeg"))],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_rendered_tc006_triage(
            claim_id,
            1,
            bill_preview_sha256=sha256(bill).hexdigest(),
        )
        document_version_id = await _document_version(factory, claim_id)
        observation_id = _observation_id(document_version_id)
        recorded_model = RecordedStructuredModelTransport(
            {
                ModelRoute.COMPLEX_EXTRACTION: {
                    "schema_version": "complex-extraction-v1",
                    "candidates": [
                        _candidate("patient.name", "Priya Singh", observation_id),
                        _candidate("billing.total", "12000.00", observation_id),
                        _candidate(
                            "billing.line_items.root_canal_treatment",
                            "8000.00",
                            observation_id,
                        ),
                        _candidate(
                            "billing.line_items.teeth_whitening",
                            "4000.00",
                            observation_id,
                        ),
                    ],
                }
            }
        )
        processor = _processor(factory, tmp_path, recorded_model)
        workflows = PostgresWorkflowRepository(factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(factory)).run_once(
            "tc006-rendered-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp002"},
        )

    assert projection.status_code == 200
    assert projection.json()["adjudication"] == {
        "recommendation": "PARTIAL",
        "approved_amount": "8000.00",
        "currency": "INR",
    }
    assert projection.json()["explanation"] == {
        "summary": "₹8,000.00 approved; ₹4,000.00 excluded from the dental claim.",
        "deductions": [
            {
                "code": "DENTAL_LINE_ITEM_EXCLUDED",
                "label": "Teeth Whitening is excluded by the dental policy.",
                "amount": "4000.00",
            }
        ],
        "line_items": [
            {
                "concept": "root_canal_treatment",
                "label": "Root Canal Treatment",
                "claimed_amount": "8000.00",
                "approved_amount": "8000.00",
                "status": "APPROVED",
                "reason_code": "DENTAL_LINE_ITEM_COVERED",
            },
            {
                "concept": "teeth_whitening",
                "label": "Teeth Whitening",
                "claimed_amount": "4000.00",
                "approved_amount": "0.00",
                "status": "REJECTED",
                "reason_code": "DENTAL_LINE_ITEM_EXCLUDED",
            },
        ],
    }
    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert [item.concept for item in trace.casefile.content.line_item_facts] == [
        "root_canal_treatment",
        "teeth_whitening",
    ]
    whitening = next(
        result
        for result in trace.rule_results
        if result.reason_code == "DENTAL_LINE_ITEM_EXCLUDED"
    )
    assert whitening.policy_path == "/opd_categories/dental/excluded_procedures/0"
    assert whitening.evidence_refs == trace.casefile.content.line_item_facts[1].evidence_refs
    category_limit = next(
        result
        for result in trace.rule_results
        if result.reason_code == "WITHIN_CATEGORY_LIMIT"
    )
    assert category_limit.inputs["eligible_paise"] == 800_000
    assert category_limit.inputs["general_limit_paise"] == 500_000
    assert category_limit.inputs["precedence"] == "CATEGORY_OVER_GENERAL"
    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_generic_dental_bill_requests_procedure_evidence(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_utilization(factory)
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    bill = _document_image("DENTAL BILL\nPatient: Priya Singh\nDental Services 12000")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp002",
                "Idempotency-Key": "tc006-generic-bill",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[("files", ("generic-dental-bill.jpg", bill, "image/jpeg"))],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_rendered_tc006_triage(
            claim_id,
            1,
            bill_preview_sha256=sha256(bill).hexdigest(),
        )
        document_version_id = await _document_version(factory, claim_id)
        observation_id = _observation_id(document_version_id)
        processor = _processor(
            factory,
            tmp_path,
            RecordedStructuredModelTransport(
                {
                    ModelRoute.COMPLEX_EXTRACTION: {
                        "schema_version": "complex-extraction-v1",
                        "candidates": [
                            _candidate("patient.name", "Priya Singh", observation_id),
                            _candidate("billing.total", "12000.00", observation_id),
                        ],
                    }
                }
            ),
        )
        workflows = PostgresWorkflowRepository(factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(factory)).run_once(
            "tc006-generic-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp002"},
        )

    assert projection.status_code == 200
    assert projection.json()["lifecycle_status"] == "ACTION_REQUIRED"
    assert "adjudication" not in projection.json()
    assert projection.json()["action"] == {
        "code": "DENTAL_PROCEDURE_EVIDENCE_REQUIRED",
        "message": (
            "The dental bill does not identify each procedure. "
            "Please upload a detailed itemized bill or a dental report."
        ),
        "observed_document_roles": ["HOSPITAL_BILL"],
        "required_document_roles": ["DENTAL_REPORT"],
    }
    await app.state.engine.dispose()
    await engine.dispose()


def _processor(factory, tmp_path: Path, recorded_model):
    page_repository = PostgresPageArtifactRepository(factory)
    ocr_repository = PostgresOcrRepository(factory)
    evidence_repository = PostgresStructuredModelRepository(factory)
    return PostgresClaimProcessor(
        factory,
        page_artifacts=PageArtifactApplication(
            LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
            LocalPageArtifactStore(tmp_path),
            page_repository,
        ),
        page_repository=page_repository,
        ocr=OcrApplication(
            LocalPageArtifactReader(tmp_path),
            Tc006RecordedOcr(),
            ocr_repository,
        ),
        ocr_repository=ocr_repository,
        structured_model=StructuredModelApplication(
            ModelRouter.default(
                region="us-west-2",
                model_id="qwen.qwen3-235b-a22b-2507-v1:0",
            ),
            recorded_model,
            evidence_repository,
        ),
        evidence_repository=evidence_repository,
    )


def _candidate(
    fact_path: str,
    value: str,
    observation_id: str,
) -> dict[str, object]:
    return {
        "fact_path": fact_path,
        "value": value,
        "normalized_value": value,
        "evidence_refs": [observation_id],
        "confidence": 0.99,
    }


def _observation_id(document_version_id: UUID) -> str:
    return sha256(
        f"{document_version_id}:{DocumentRole.HOSPITAL_BILL.value}".encode()
    ).hexdigest()


async def _document_version(factory, claim_id: UUID) -> UUID:
    async with factory() as session:
        return (
            await session.scalars(
                select(DocumentVersionRow.id)
                .join(DocumentRow)
                .where(DocumentRow.claim_id == claim_id)
            )
        ).one()


async def _import_utilization(factory) -> None:
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-10-15",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP002",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "0.00",
                        "currency": "INR",
                        "as_of_date": "2024-10-15",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc006-rendered-member-facts.json",
    )


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP002",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "DENTAL",
        "treatment_date": "2024-10-15",
        "claimed_amount": "12000.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "F011"}],
    }


def _document_image(text: str) -> bytes:
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 60), text, fill="black", spacing=20)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
