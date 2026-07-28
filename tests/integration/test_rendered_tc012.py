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


class Tc012RecordedOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "tc012-rendered-v1"

    def analyze(self, page, role: DocumentRole) -> OcrPageResult:
        observation_id = _observation_id(page.document_version_id, role)
        return OcrPageResult(
            profile=(
                TextractProfile.EXPENSE
                if role is DocumentRole.HOSPITAL_BILL
                else TextractProfile.FORMS_TABLES
            ),
            provider_request_id=f"tc012-{page.document_version_id}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=1,
                    kind=OcrObservationKind.LINE,
                    text=(
                        "Morbid Obesity BMI 37 Bariatric Consultation Customised Diet Plan"
                        if role is DocumentRole.PRESCRIPTION
                        else (
                            "Bariatric Consultation 3000 "
                            "Personalised Diet and Nutrition Program 5000 Total 8000"
                        )
                    ),
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.3),
                    source_id="recorded-line-1",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_rendered_tc012_rejects_grounded_obesity_treatment_exclusion(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_utilization(factory)
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    prescription = _document_image(
        "PRESCRIPTION\nDiagnosis: Morbid Obesity — BMI 37\n"
        "Treatment: Bariatric Consultation and Customised Diet Plan"
    )
    bill = _document_image(
        "HOSPITAL BILL\nBariatric Consultation 3000\n"
        "Personalised Diet and Nutrition Program 5000\nTotal 8000"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp009",
                "Idempotency-Key": "tc012-rendered",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
                ("files", ("hospital-bill.jpg", bill, "image/jpeg")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_rendered_tc012_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(bill).hexdigest(),
        )
        versions = await _document_versions(factory, claim_id)
        prescription_id = versions["F023"]
        bill_id = versions["F024"]
        recorded_model = RecordedStructuredModelTransport(
            {
                ModelRoute.COMPLEX_EXTRACTION: (
                    {
                        "schema_version": "complex-extraction-v1",
                        "candidates": [
                            _candidate(
                                "clinical.condition",
                                "Morbid Obesity — BMI 37",
                                prescription_id,
                                DocumentRole.PRESCRIPTION,
                            ),
                            _candidate(
                                "clinical.treatment",
                                "Bariatric Consultation and Customised Diet Plan",
                                prescription_id,
                                DocumentRole.PRESCRIPTION,
                            ),
                        ],
                    },
                    {
                        "schema_version": "complex-extraction-v1",
                        "candidates": [
                            _candidate(
                                "billing.total",
                                "8000.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _candidate(
                                "billing.line_items.bariatric_consultation",
                                "3000.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _candidate(
                                "billing.line_items.nutrition_program",
                                "5000.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                        ],
                    },
                )
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
            "tc012-rendered-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp009"},
        )

    assert projection.status_code == 200
    assert projection.json()["adjudication"] == {
        "recommendation": "REJECTED",
        "approved_amount": "0.00",
        "currency": "INR",
    }
    assert projection.json()["explanation"] == {
        "summary": (
            "This claim is excluded because Obesity and weight loss programs "
            "are not covered by the policy."
        ),
        "deductions": [
            {
                "code": "EXCLUDED_CONDITION",
                "label": "Obesity and weight loss programs",
                "amount": "8000.00",
            }
        ],
    }
    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert trace.casefile.content.clinical_condition is not None
    assert trace.casefile.content.clinical_condition.value == "obesity"
    assert trace.casefile.content.clinical_treatment is not None
    assert trace.casefile.content.clinical_treatment.value == "bariatric_treatment"
    exclusion = trace.rule_results[-1]
    assert exclusion.reason_code == "EXCLUDED_CONDITION"
    assert exclusion.policy_path == "/exclusions/conditions/5"
    assert exclusion.evidence_refs == (
        *trace.casefile.content.clinical_condition.evidence_refs,
    )
    supporting = [
        candidate
        for candidate in trace.casefile.content.evidence.candidates
        if candidate.candidate_id in exclusion.evidence_refs
    ]
    assert supporting
    assert all(candidate.confidence > 0.90 for candidate in supporting)
    assert all(
        source.document_version_id is not None and source.page == 1
        for candidate in supporting
        for source in candidate.sources
    )
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
            Tc012RecordedOcr(),
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
    document_version_id: UUID,
    role: DocumentRole,
) -> dict[str, object]:
    return {
        "fact_path": fact_path,
        "value": value,
        "normalized_value": value,
        "evidence_refs": [_observation_id(document_version_id, role)],
        "confidence": 0.99,
    }


def _observation_id(document_version_id: UUID, role: DocumentRole) -> str:
    return sha256(f"{document_version_id}:{role.value}".encode()).hexdigest()


async def _document_versions(factory, claim_id: UUID) -> dict[str, UUID]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(DocumentRow.client_document_id, DocumentVersionRow.id)
                .join(DocumentVersionRow)
                .where(DocumentRow.claim_id == claim_id)
            )
        ).all()
    return dict(rows)


async def _import_utilization(factory) -> None:
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-10-18",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP009",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "0.00",
                        "currency": "INR",
                        "as_of_date": "2024-10-18",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc012-rendered-member-facts.json",
    )


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP009",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-18",
        "claimed_amount": "8000.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F023"},
            {"upload_index": 1, "client_document_id": "F024"},
        ],
    }


def _document_image(text: str) -> bytes:
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 60), text, fill="black", spacing=20)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
