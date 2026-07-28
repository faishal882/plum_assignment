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
from claims_backend.infrastructure.postgres.models import (
    DocumentRow,
    DocumentVersionRow,
    WorkflowRunRow,
)
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


class Tc004RecordedOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "tc004-rendered-v1"

    def analyze(self, page, role: DocumentRole) -> OcrPageResult:
        observation_id = _observation_id(page.document_version_id, role)
        return OcrPageResult(
            profile=(
                TextractProfile.EXPENSE
                if role is DocumentRole.HOSPITAL_BILL
                else TextractProfile.FORMS_TABLES
            ),
            provider_request_id=f"tc004-{page.document_version_id}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=1,
                    kind=OcrObservationKind.LINE,
                    text=(
                        "Rajesh Kumar 2024-11-01 Viral Fever"
                        if role is DocumentRole.PRESCRIPTION
                        else "Rajesh Kumar 2024-11-01 Consultation 1000 CBC 300 NS1 200 Total 1500"
                    ),
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.2),
                    source_id="recorded-line-1",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_rendered_tc004_runs_the_real_recorded_pipeline_to_exact_approval(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_utilization(factory)
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    prescription = _document_image(
        "PRESCRIPTION\nPatient: Rajesh Kumar\nDate: 2024-11-01\nDiagnosis: Viral Fever"
    )
    bill = _document_image(
        "HOSPITAL BILL\nPatient: Rajesh Kumar\nConsultation 1000\nCBC 300\nNS1 200\nTotal 1500"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc004-rendered",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
                ("files", ("hospital-bill.jpg", bill, "image/jpeg")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_rendered_tc004_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(bill).hexdigest(),
        )
        versions = await _document_versions(factory, claim_id)
        prescription_id = versions["F007"]
        bill_id = versions["F008"]
        recorded_model = RecordedStructuredModelTransport(
            {
                ModelRoute.COMPLEX_EXTRACTION: (
                    {
                        "schema_version": "complex-extraction-v1",
                        "candidates": [
                            _model_candidate("patient.name", "Rajesh Kumar", prescription_id),
                            _model_candidate("treatment.date", "2024-11-01", prescription_id),
                            _model_candidate("clinical.condition", "Viral Fever", prescription_id),
                        ],
                    },
                    {
                        "schema_version": "complex-extraction-v1",
                        "candidates": [
                            _model_candidate(
                                "patient.name",
                                "Rajesh Kumar",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _model_candidate(
                                "treatment.date",
                                "2024-11-01",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _model_candidate(
                                "billing.total",
                                "1500.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _model_candidate(
                                "billing.line_items.consultation_fee",
                                "1000.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _model_candidate(
                                "billing.line_items.cbc",
                                "300.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                            _model_candidate(
                                "billing.line_items.ns1",
                                "200.00",
                                bill_id,
                                DocumentRole.HOSPITAL_BILL,
                            ),
                        ],
                    },
                )
            }
        )
        page_repository = PostgresPageArtifactRepository(factory)
        ocr_repository = PostgresOcrRepository(factory)
        evidence_repository = PostgresStructuredModelRepository(factory)
        processor = PostgresClaimProcessor(
            factory,
            page_artifacts=PageArtifactApplication(
                LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
                LocalPageArtifactStore(tmp_path),
                page_repository,
            ),
            page_repository=page_repository,
            ocr=OcrApplication(
                LocalPageArtifactReader(tmp_path),
                Tc004RecordedOcr(),
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
        workflows = PostgresWorkflowRepository(factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(factory)).run_once(
            "tc004-rendered-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        async with factory() as session:
            rendered_run = (
                await session.scalars(
                    select(WorkflowRunRow).where(WorkflowRunRow.claim_id == claim_id)
                )
            ).one()
        rendered_effects = await workflows.list_effects(rendered_run.id)
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )
        structured_submission = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc004-structured-comparison",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
                ("files", ("hospital-bill.jpg", bill, "image/jpeg")),
            ],
        )
        assert structured_submission.status_code == 202
        structured_claim_id = UUID(structured_submission.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_tc004(
            structured_claim_id,
            1,
        )
        assert await WorkerService(PostgresWorkScheduler(factory)).run_once(
            "tc004-structured-comparison-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )

    assert projection.status_code == 200
    assert [effect.effect_type for effect in rendered_effects] == [
        "CLAIM_VERSION_LOADED",
        "LOCAL_MEDIA_INSPECTED",
        "DOCUMENT_TRIAGE_COMPLETED",
        "DOCUMENT_PAGES_RENDERED",
        "PAGE_OCR_COMPLETED",
        "STRUCTURED_EXTRACTION_COMPLETED",
        "EVIDENCE_RECONCILED",
        "CASEFILE_FROZEN",
        "ADJUDICATION_PROPOSED",
        "DECISION_COMMITTED",
    ]
    assert projection.json()["adjudication"] == {
        "recommendation": "APPROVED",
        "approved_amount": "1350.00",
        "currency": "INR",
    }
    assert projection.json()["explanation"]["deductions"] == [
        {
            "code": "CATEGORY_COPAY_APPLIED",
            "label": "10% consultation co-pay",
            "amount": "150.00",
        }
    ]
    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert trace.casefile.content.schema_version == 5
    assert trace.casefile.content.evidence is not None
    assert trace.casefile.content.billed_paise.value == 150_000
    assert trace.casefile.content.clinical_condition.value == "viral fever"
    assert all(
        source.document_version_id is not None and source.page == 1
        for candidate in trace.casefile.content.evidence.candidates
        if candidate.producer == "BEDROCK"
        for source in candidate.sources
    )
    assert [result.amount_after_paise for result in trace.rule_results][-1] == 135_000
    structured_trace = await processor.inspect_trace(structured_claim_id)
    assert structured_trace is not None
    assert _material_signature(structured_trace.casefile.content) == _material_signature(
        trace.casefile.content
    )
    assert _decision_signature(structured_trace) == _decision_signature(trace)
    await app.state.engine.dispose()
    await engine.dispose()


def _model_candidate(
    fact_path: str,
    value: str,
    document_version_id: UUID,
    role: DocumentRole = DocumentRole.PRESCRIPTION,
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


async def _document_versions(
    factory,
    claim_id: UUID,
) -> dict[str, UUID]:
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
                "as_of_date": "2024-11-01",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP001",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "5000.00",
                        "currency": "INR",
                        "as_of_date": "2024-11-01",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc004-rendered-member-facts.json",
    )


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F007"},
            {"upload_index": 1, "client_document_id": "F008"},
        ],
    }


def _document_image(text: str) -> bytes:
    image = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((60, 60), text, fill="black", spacing=20)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def _material_signature(casefile) -> tuple[object, ...]:
    return (
        casefile.claimed_amount.value,
        casefile.billed_paise.value,
        casefile.treatment_date.value,
        casefile.member_join_date.value,
        casefile.patient_identity.value,
        casefile.clinical_condition.value,
        casefile.line_items.value,
    )


def _decision_signature(trace) -> tuple[object, ...]:
    return (
        trace.decision.recommendation,
        trace.decision.approved_paise,
        tuple(
            (
                result.rule_id,
                result.status,
                result.reason_code,
                result.policy_path,
                result.inputs,
                result.amount_before_paise,
                result.adjustment_paise,
                result.amount_after_paise,
            )
            for result in trace.rule_results
        ),
    )
