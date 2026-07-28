import json
import re
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import OcrApplication, PageArtifactApplication
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.evidence import (
    DocumentRole,
    IdentityObservation,
    NormalizedRegion,
    PreviewProvenance,
    Readability,
    ReadabilityObservation,
    StructuredDocumentEvidence,
    StructuredEvidencePayload,
    TriageDocumentResult,
    TriageIdentityObservation,
    TriageModelOutput,
)
from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    TextractProfile,
)
from claims_backend.infrastructure.fixtures.document_quality import (
    degrade_to_unreadable_jpeg,
)
from claims_backend.infrastructure.fixtures.failures import (
    EvaluationAnomalyFailureInjector,
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
from claims_backend.infrastructure.postgres.reconstruction import (
    PostgresClaimReconstructor,
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
from claims_backend.observability import (
    EngineeringLogEvent,
    ObservabilityConfig,
    create_observability,
    scan_telemetry_for_phi,
)
from evaluation_workbench import (
    ActualCaseResult,
    EvaluationRunBuilder,
    ExecutionProfile,
    OracleScorer,
    OutcomeSnapshot,
    SourceVersions,
    execution_guard,
    load_evaluation_inputs,
)

_DATASET_PATH = Path("problem_statement/test_cases.json")
_POLICY_PATH = Path("problem_statement/policy_terms.json")
_OVERLAY_PATH = Path("config/policy/assignment-overlay-v1.json")
_DATASET_BYTES = _DATASET_PATH.read_bytes()
_POLICY_BYTES = _POLICY_PATH.read_bytes()
_OVERLAY_BYTES = _OVERLAY_PATH.read_bytes()
_RAW_DATASET = json.loads(_DATASET_BYTES)
_MODEL_ID = "qwen.qwen3-235b-a22b-2507-v1:0"
_MEMBER_NAMES = {
    "EMP001": "Rajesh Kumar",
    "EMP002": "Priya Singh",
    "EMP003": "Amit Verma",
    "EMP004": "Sneha Reddy",
    "EMP005": "Vikram Joshi",
    "EMP006": "Kavita Nair",
    "EMP007": "Suresh Patil",
    "EMP008": "Ravi Menon",
    "EMP009": "Anita Desai",
    "EMP010": "Deepak Shah",
}


class RecordedRenderedOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "rendered-evaluation-v1"

    def __init__(
        self,
        documents: dict[UUID, tuple[DocumentRole, str]],
    ) -> None:
        self._documents = documents

    def analyze(self, page: Any, role: DocumentRole) -> OcrPageResult:
        expected_role, text = self._documents[page.document_version_id]
        if role is not expected_role:
            raise AssertionError("Recorded OCR role does not match triage")
        return OcrPageResult(
            profile=(
                TextractProfile.EXPENSE
                if role in {DocumentRole.HOSPITAL_BILL, DocumentRole.PHARMACY_BILL}
                else TextractProfile.FORMS_TABLES
            ),
            provider_request_id=f"recorded-{page.document_version_id}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=_observation_id(page.document_version_id, role),
                    document_version_id=page.document_version_id,
                    page_number=page.page_number,
                    kind=OcrObservationKind.LINE,
                    text=text,
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.5),
                    source_id="recorded-line-1",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_all_twelve_cases_pass_the_recorded_rendered_evaluation_gate(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    raw_dataset = _RAW_DATASET
    dataset = load_evaluation_inputs(_DATASET_PATH)
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_evaluation_facts(factory, raw_dataset)
    exporter = InMemorySpanExporter()
    observability_config = ObservabilityConfig(
        log_root=tmp_path / "diagnostics",
        execution_profile=ExecutionProfile.RENDERED_RECORDED.value,
        phi_canaries=tuple(_MEMBER_NAMES.values()),
    )
    api_observability = create_observability(
        observability_config,
        process_name="api",
        span_exporter=exporter,
    )
    worker_observability = create_observability(
        observability_config,
        process_name="worker",
        span_exporter=exporter,
    )
    evaluation_observability = create_observability(
        observability_config,
        process_name="evaluation",
        span_exporter=exporter,
    )
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path / "documents"),
        observability=api_observability,
    )
    builder = EvaluationRunBuilder(dataset, _source_versions(raw_dataset))
    reconstructor = PostgresClaimReconstructor(factory)

    with execution_guard(
        ExecutionProfile.RENDERED_RECORDED,
        synthetic_only=True,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            for raw_case in raw_dataset["test_cases"]:
                case_id = raw_case["case_id"]
                with evaluation_observability.span(
                    "evaluation.case",
                    component="evaluation",
                    attributes={
                        "evaluation.case_id": case_id,
                        "evaluation.profile": ExecutionProfile.RENDERED_RECORDED.value,
                    },
                ) as evaluation_span:
                    result, claim_id, workflow_run_id = await _run_rendered_case(
                        app,
                        client,
                        factory,
                        migrated_database_url,
                        tmp_path / "documents",
                        raw_case,
                        worker_observability,
                        reconstructor,
                    )
                    builder.record(result)
                    evaluation_observability.set_attributes(
                        evaluation_span,
                        {
                            "claim.id": str(claim_id),
                            "workflow.run_id": workflow_run_id,
                        },
                    )
                    evaluation_observability.log(
                        EngineeringLogEvent(
                            event_name="evaluation_case_finished",
                            component="evaluation",
                            claim_id=str(claim_id),
                            workflow_run_id=workflow_run_id,
                            attempt=1,
                            duration_ms=0,
                            outcome="OK",
                        )
                    )

    run = builder.finalize()
    report = OracleScorer.score(_DATASET_PATH, run)
    report_path = tmp_path / "evaluation-report.json"
    report_path.write_text(report.model_dump_json(indent=2))

    assert report.passed is True, {
        case.case_id: case.mismatches for case in report.cases if not case.passed
    }
    assert [case.case_id for case in report.cases] == [
        f"TC{number:03d}" for number in range(1, 13)
    ]
    assert all(case.actual.trace_complete for case in report.cases)
    assert report.versions.execution_profile is ExecutionProfile.RENDERED_RECORDED
    assert report.versions.ocr_mode == "ENABLED"
    assert report_path.is_file()
    records: dict[str, list[dict[str, object]]] = {}
    for process in ("api", "worker", "evaluation"):
        path = tmp_path / "diagnostics" / f"{process}.jsonl"
        assert path.is_file()
        records[process] = [
            json.loads(line) for line in path.read_text().splitlines() if line
        ]
        assert any(
            all(
                record[field] is not None
                for field in (
                    "claim_id",
                    "workflow_run_id",
                    "trace_id",
                    "span_id",
                    "attempt",
                    "duration_ms",
                    "outcome",
                )
            )
            for record in records[process]
        )
    scan_telemetry_for_phi(
        [
            record
            for process_records in records.values()
            for record in process_records
        ],
        phi_canaries=tuple(_MEMBER_NAMES.values()),
    )
    scan_telemetry_for_phi(
        [dict(span.attributes) for span in exporter.get_finished_spans()],
        phi_canaries=tuple(_MEMBER_NAMES.values()),
    )

    api_observability.shutdown()
    worker_observability.shutdown()
    evaluation_observability.shutdown()
    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_twelve_cases_pass_the_ocr_bypassed_structured_gate(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    raw_dataset = _RAW_DATASET
    dataset = load_evaluation_inputs(_DATASET_PATH)
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_evaluation_facts(factory, raw_dataset)
    exporter = InMemorySpanExporter()
    worker_observability = create_observability(
        ObservabilityConfig(
            log_root=tmp_path / "diagnostics",
            execution_profile=ExecutionProfile.STRUCTURED_COMPONENT.value,
        ),
        process_name="worker",
        span_exporter=exporter,
    )
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path / "documents")
    )
    builder = EvaluationRunBuilder(
        dataset,
        _source_versions(
            raw_dataset,
            profile=ExecutionProfile.STRUCTURED_COMPONENT,
        ),
    )
    reconstructor = PostgresClaimReconstructor(factory)

    with execution_guard(
        ExecutionProfile.STRUCTURED_COMPONENT,
        synthetic_only=True,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            for raw_case in raw_dataset["test_cases"]:
                builder.record(
                    await _run_structured_case(
                        client,
                        factory,
                        migrated_database_url,
                        raw_case,
                        worker_observability,
                        reconstructor,
                    )
                )

    run = builder.finalize()
    report = OracleScorer.score(_DATASET_PATH, run)

    assert report.passed is True, {
        case.case_id: case.mismatches for case in report.cases if not case.passed
    }
    assert report.versions.execution_profile is ExecutionProfile.STRUCTURED_COMPONENT
    assert report.versions.ocr_mode == "BYPASSED"
    assert not any(
        span.name in {"textract.analyze", "bedrock.converse"}
        for span in exporter.get_finished_spans()
    )
    worker_observability.shutdown()
    await app.state.engine.dispose()
    await engine.dispose()


async def _run_rendered_case(
    app: Any,
    client: AsyncClient,
    factory: async_sessionmaker,
    database_url: str,
    document_root: Path,
    raw_case: dict[str, Any],
    worker_observability: Any,
    reconstructor: PostgresClaimReconstructor,
) -> tuple[ActualCaseResult, UUID, str]:
    case_id = str(raw_case["case_id"])
    inputs = raw_case["input"]
    member_id = str(inputs["member_id"])
    rendered = _render_documents(inputs)
    claim_id = await _submit_claim(
        client,
        raw_case,
        rendered,
        idempotency_suffix="rendered-gate",
    )
    triage = _triage_output(raw_case, rendered)
    await StructuredComponentFixtureAdapter(factory).seed_recorded_triage(
        claim_id,
        1,
        triage,
    )
    document_versions = await _document_versions(factory, claim_id)
    processor = _processor(
        factory,
        document_root,
        raw_case,
        document_versions,
    )
    if case_id == "TC011":
        processor = _processor(
            factory,
            document_root,
            raw_case,
            document_versions,
            anomaly_enricher=EvaluationAnomalyFailureInjector(),
        )
    workflows = PostgresWorkflowRepository(factory)
    runtime = LangGraphClaimWorkflow(
        database_url,
        workflows,
        processor=processor,
        observability=worker_observability,
    )
    await runtime.setup()
    processed = await WorkerService(PostgresWorkScheduler(factory)).run_once(
        f"{case_id.casefold()}-rendered-worker",
        ClaimWorkflowProcessor(workflows, runtime).process,
    )
    assert processed is True
    if case_id == "TC009":
        listed = await client.get(
            "/v1/review-tasks",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        assert listed.status_code == 200
        task_id = listed.json()[0]["id"]
        inspected = await client.get(
            f"/v1/review-tasks/{task_id}",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        assert inspected.status_code == 200
    projection = await client.get(
        f"/v1/claims/{claim_id}",
        headers={"X-Dev-Username": f"member.{member_id.casefold()}"},
    )
    assert projection.status_code == 200
    reconstruction = await reconstructor.reconstruct(claim_id)
    assert reconstruction is not None
    assert reconstruction.workflow is not None
    return (
        _actual_result(case_id, raw_case, reconstruction),
        claim_id,
        str(reconstruction.workflow["id"]),
    )


async def _run_structured_case(
    client: AsyncClient,
    factory: async_sessionmaker,
    database_url: str,
    raw_case: dict[str, Any],
    worker_observability: Any,
    reconstructor: PostgresClaimReconstructor,
) -> ActualCaseResult:
    case_id = str(raw_case["case_id"])
    rendered = _render_documents(raw_case["input"])
    claim_id = await _submit_claim(
        client,
        raw_case,
        rendered,
        idempotency_suffix="structured-gate",
    )
    fixtures = StructuredComponentFixtureAdapter(factory)
    if case_id in {"TC001", "TC002", "TC003"}:
        await fixtures.seed_recorded_triage(
            claim_id,
            1,
            _triage_output(raw_case, rendered),
        )
    else:
        await fixtures.seed_recorded_structured(
            claim_id,
            1,
            _structured_payload(raw_case),
        )
    processor = PostgresClaimProcessor(
        factory,
        anomaly_enricher=(
            EvaluationAnomalyFailureInjector() if case_id == "TC011" else None
        ),
    )
    workflows = PostgresWorkflowRepository(factory)
    runtime = LangGraphClaimWorkflow(
        database_url,
        workflows,
        processor=processor,
        observability=worker_observability,
    )
    await runtime.setup()
    assert await WorkerService(PostgresWorkScheduler(factory)).run_once(
        f"{case_id.casefold()}-structured-worker",
        ClaimWorkflowProcessor(workflows, runtime).process,
    )
    reconstruction = await reconstructor.reconstruct(claim_id)
    assert reconstruction is not None
    return _actual_result(case_id, raw_case, reconstruction)


async def _submit_claim(
    client: AsyncClient,
    raw_case: dict[str, Any],
    rendered: tuple[bytes, ...],
    *,
    idempotency_suffix: str,
) -> UUID:
    case_id = str(raw_case["case_id"])
    inputs = raw_case["input"]
    member_id = str(inputs["member_id"])
    metadata = {
        "member_id": member_id,
        "policy_id": inputs["policy_id"],
        "claim_category": inputs["claim_category"],
        "treatment_date": inputs["treatment_date"],
        "claimed_amount": f"{float(inputs['claimed_amount']):.2f}",
        "currency": "INR",
        "documents": [
            {"upload_index": index, "client_document_id": document["file_id"]}
            for index, document in enumerate(inputs["documents"])
        ],
    }
    submitted = await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": f"member.{member_id.casefold()}",
            "Idempotency-Key": f"{case_id.casefold()}-{idempotency_suffix}",
        },
        data={"metadata": json.dumps(metadata)},
        files=[
            (
                "files",
                (
                    str(document.get("file_name", f"{document['file_id']}.jpg")),
                    content,
                    "image/jpeg",
                ),
            )
            for document, content in zip(
                inputs["documents"],
                rendered,
                strict=True,
            )
        ],
    )
    assert submitted.status_code == 202, submitted.text
    return UUID(submitted.json()["claim_id"])


def _processor(
    factory: async_sessionmaker,
    document_root: Path,
    raw_case: dict[str, Any],
    document_versions: dict[str, UUID],
    *,
    anomaly_enricher: Any = None,
) -> PostgresClaimProcessor:
    case_id = str(raw_case["case_id"])
    if case_id in {"TC001", "TC002", "TC003"}:
        return PostgresClaimProcessor(factory, anomaly_enricher=anomaly_enricher)
    documents = raw_case["input"]["documents"]
    ocr_documents: dict[UUID, tuple[DocumentRole, str]] = {}
    responses: list[dict[str, object]] = []
    for document in documents:
        client_id = str(document["file_id"])
        role = DocumentRole(str(document["actual_type"]))
        version_id = document_versions[client_id]
        content = document.get("content", {})
        ocr_documents[version_id] = (
            role,
            json.dumps(content, sort_keys=True, separators=(",", ":")),
        )
        responses.append(
            {
                "schema_version": "complex-extraction-v1",
                "candidates": _candidates(
                    raw_case,
                    document,
                    version_id,
                    role,
                ),
            }
        )
    page_repository = PostgresPageArtifactRepository(factory)
    ocr_repository = PostgresOcrRepository(factory)
    evidence_repository = PostgresStructuredModelRepository(factory)
    return PostgresClaimProcessor(
        factory,
        page_artifacts=PageArtifactApplication(
            LocalPageRenderer(document_root, max_page_bytes=5 * 1024 * 1024),
            LocalPageArtifactStore(document_root),
            page_repository,
        ),
        page_repository=page_repository,
        ocr=OcrApplication(
            LocalPageArtifactReader(document_root),
            RecordedRenderedOcr(ocr_documents),
            ocr_repository,
        ),
        ocr_repository=ocr_repository,
        structured_model=StructuredModelApplication(
            ModelRouter.default(region="us-west-2", model_id=_MODEL_ID),
            RecordedStructuredModelTransport(
                {ModelRoute.COMPLEX_EXTRACTION: tuple(responses)}
            ),
            evidence_repository,
        ),
        evidence_repository=evidence_repository,
        anomaly_enricher=anomaly_enricher,
    )


def _candidates(
    raw_case: dict[str, Any],
    document: dict[str, Any],
    document_version_id: UUID,
    role: DocumentRole,
) -> list[dict[str, object]]:
    content = document.get("content")
    values = content if isinstance(content, dict) else {}
    reference = _observation_id(document_version_id, role)
    candidates: list[dict[str, object]] = []

    def add(path: str, value: object) -> None:
        if value is None:
            return
        rendered = str(value)
        candidates.append(
            {
                "fact_path": path,
                "value": rendered,
                "normalized_value": rendered,
                "evidence_refs": [reference],
                "confidence": 0.99,
            }
        )

    member_id = str(raw_case["input"]["member_id"])
    add("patient.name", values.get("patient_name", _MEMBER_NAMES[member_id]))
    add("treatment.date", values.get("date", raw_case["input"]["treatment_date"]))
    add("clinical.condition", values.get("diagnosis"))
    treatment = values.get("treatment")
    if treatment is None:
        ordered = values.get("tests_ordered")
        treatment = ordered[0] if isinstance(ordered, list) and ordered else None
    if treatment is None:
        treatment = values.get("test_name")
    if treatment is not None and "mri" in str(treatment).casefold():
        treatment = "MRI"
    add("clinical.treatment", treatment)
    add("provider.name", values.get("hospital_name"))
    total = values.get("total")
    if isinstance(total, int | float):
        add("billing.total", f"{float(total):.2f}")
    line_items = values.get("line_items")
    if isinstance(line_items, list):
        for item in line_items:
            if not isinstance(item, dict):
                continue
            description = item.get("description")
            amount = item.get("amount")
            if isinstance(description, str) and isinstance(amount, int | float):
                add(
                    f"billing.line_items.{_slug(description)}",
                    f"{float(amount):.2f}",
                )
    return candidates


def _triage_output(
    raw_case: dict[str, Any],
    rendered: tuple[bytes, ...],
) -> TriageModelOutput:
    inputs = raw_case["input"]
    member_name = _MEMBER_NAMES[str(inputs["member_id"])]
    documents: list[TriageDocumentResult] = []
    for document, content in zip(inputs["documents"], rendered, strict=True):
        identity_name = document.get("patient_name_on_doc", member_name)
        readable = (
            Readability.UNREADABLE
            if document.get("quality") == "UNREADABLE"
            else Readability.READABLE
        )
        documents.append(
            TriageDocumentResult(
                client_document_id=str(document["file_id"]),
                role=DocumentRole(str(document["actual_type"])),
                readability=ReadabilityObservation(
                    status=readable,
                    preview=PreviewProvenance(
                        page=1,
                        sha256=sha256(content).hexdigest(),
                        transform_version="rendered-evaluation-v1",
                    ),
                ),
                identity_observations=(
                    TriageIdentityObservation(
                        kind="PATIENT_NAME",
                        value=str(identity_name),
                        page=1,
                        region=NormalizedRegion(
                            x=0.1,
                            y=0.2,
                            width=0.5,
                            height=0.1,
                        ),
                        source_text_sha256=sha256(
                            str(identity_name).encode()
                        ).hexdigest(),
                        confidence=0.99,
                    ),
                ),
            )
        )
    return TriageModelOutput(documents=tuple(documents))


def _structured_payload(raw_case: dict[str, Any]) -> StructuredEvidencePayload:
    inputs = raw_case["input"]
    member_name = _MEMBER_NAMES[str(inputs["member_id"])]
    documents: list[StructuredDocumentEvidence] = []
    for document in inputs["documents"]:
        values = document.get("content")
        content = values if isinstance(values, dict) else {}
        treatment = content.get("treatment")
        if treatment is None:
            ordered = content.get("tests_ordered")
            treatment = ordered[0] if isinstance(ordered, list) and ordered else None
        if treatment is None:
            treatment = content.get("test_name")
        if treatment is not None and "mri" in str(treatment).casefold():
            treatment = "MRI"
        line_items: dict[str, int] = {}
        raw_line_items = content.get("line_items")
        if isinstance(raw_line_items, list):
            for item in raw_line_items:
                if not isinstance(item, dict):
                    continue
                description = item.get("description")
                amount = item.get("amount")
                if isinstance(description, str) and isinstance(amount, int | float):
                    line_items[_slug(description)] = int(round(float(amount) * 100))
        total = content.get("total")
        identity_name = document.get("patient_name_on_doc")
        if identity_name is None:
            identity_name = content.get("patient_name", member_name)
        documents.append(
            StructuredDocumentEvidence(
                evidence_id=str(document["file_id"]),
                client_document_id=str(document["file_id"]),
                role=DocumentRole(str(document["actual_type"])),
                readability=(
                    Readability.UNREADABLE
                    if document.get("quality") == "UNREADABLE"
                    else Readability.READABLE
                ),
                identity_observations=(
                    IdentityObservation(
                        kind="PATIENT_NAME",
                        value=str(identity_name),
                    ),
                ),
                billed_paise=(
                    int(round(float(total) * 100))
                    if isinstance(total, int | float)
                    else None
                ),
                treatment_date=str(
                    content.get("date", inputs["treatment_date"])
                ),
                clinical_condition=(
                    None
                    if content.get("diagnosis") is None
                    else str(content["diagnosis"])
                ),
                clinical_treatment=(
                    None if treatment is None else str(treatment)
                ),
                provider_name=(
                    None
                    if content.get("hospital_name") is None
                    else str(content["hospital_name"])
                ),
                line_items_paise=line_items,
            )
        )
    return StructuredEvidencePayload(documents=tuple(documents))


def _render_documents(inputs: dict[str, Any]) -> tuple[bytes, ...]:
    rendered: list[bytes] = []
    for document in inputs["documents"]:
        body = json.dumps(
            document.get("content", {}),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
        content = _document_image(f"{document['actual_type']}\n{body}")
        if document.get("quality") == "UNREADABLE":
            content = degrade_to_unreadable_jpeg(content)
        rendered.append(content)
    return tuple(rendered)


def _document_image(text: str) -> bytes:
    image = Image.new("RGB", (1400, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((80, 80), text, fill="black", spacing=14)
    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=False, progressive=False)
    return output.getvalue()


async def _document_versions(
    factory: async_sessionmaker,
    claim_id: UUID,
) -> dict[str, UUID]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(DocumentRow.client_document_id, DocumentVersionRow.id)
                .join(DocumentVersionRow)
                .where(DocumentRow.claim_id == claim_id)
                .order_by(DocumentRow.upload_index)
            )
        ).all()
    return dict(rows)


def _actual_result(
    case_id: str,
    raw_case: dict[str, Any],
    reconstruction: Any,
) -> ActualCaseResult:
    claim = reconstruction.claim
    review = reconstruction.review_task
    reasons = {
        str(rule["reason_code"])
        for rule in reconstruction.rule_results
        if rule.get("reason_code")
    }
    reasons.update(str(action["code"]) for action in reconstruction.member_actions)
    if review is not None:
        reasons.update(str(value) for value in review["signal_codes"])
    provenance = {
        str(document["file_id"]) for document in raw_case["input"]["documents"]
    }
    provenance.update(reconstruction.evidence_references)
    return ActualCaseResult(
        case_id=case_id,
        outcome=OutcomeSnapshot(
            lifecycle=str(claim["lifecycle_status"]),
            adjudication=(
                "MANUAL_REVIEW"
                if review is not None and review["status"] == "OPEN"
                else (
                    None
                    if claim["adjudication_recommendation"] is None
                    else str(claim["adjudication_recommendation"])
                )
            ),
            approved_paise=(
                None
                if claim["approved_paise"] is None
                else int(claim["approved_paise"])
            ),
            reason_codes=tuple(sorted(reasons)),
            provenance=tuple(sorted(provenance)),
            trace_complete=_trace_complete(reconstruction.workflow_events),
            assumptions=(),
            failures=tuple(
                sorted(str(failure["component"]) for failure in reconstruction.component_failures)
            ),
        ),
    )


def _trace_complete(events: tuple[dict[str, object], ...]) -> bool:
    if not events:
        return False
    entries: dict[tuple[str, int], int] = {}
    terminals: dict[tuple[str, int], int] = {}
    for event in events:
        if event["trace_id"] is None or event["span_id"] is None:
            return False
        key = (str(event["node_name"]), int(event["attempt_number"]))
        if event["event_type"] == "ENTRY":
            entries[key] = entries.get(key, 0) + 1
        elif event["event_type"] in {"EXIT", "ERROR"}:
            terminals[key] = terminals.get(key, 0) + 1
    return bool(entries) and entries == terminals


async def _import_evaluation_facts(
    factory: async_sessionmaker,
    raw_dataset: dict[str, Any],
) -> None:
    history: list[dict[str, object]] = []
    utilization_by_member: dict[str, dict[str, object]] = {}
    for case in raw_dataset["test_cases"]:
        inputs = case["input"]
        member_id = inputs["member_id"]
        used_amount = float(inputs.get("ytd_claims_amount", 0))
        existing = utilization_by_member.get(member_id)
        if existing is None or used_amount > float(existing["used_amount"]):
            utilization_by_member[member_id] = {
                "member_id": member_id,
                "period_start": "2024-04-01",
                "period_end": "2025-03-31",
                "used_amount": f"{used_amount:.2f}",
                "currency": "INR",
                "as_of_date": inputs["treatment_date"],
            }
        for previous in inputs.get("claims_history", []):
            history.append(
                {
                    "history_claim_id": previous["claim_id"],
                    "member_id": member_id,
                    "treatment_date": previous["date"],
                    "amount": f"{float(previous['amount']):.2f}",
                    "currency": "INR",
                    "provider": previous["provider"],
                }
            )
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
        source_name=_POLICY_PATH.name,
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-11-03",
                "claim_history": history,
                "utilization": list(utilization_by_member.values()),
            }
        ).encode(),
        member_data_source_name="rendered-evaluation-facts-v1.json",
    )


def _source_versions(
    raw_dataset: dict[str, Any],
    *,
    profile: ExecutionProfile = ExecutionProfile.RENDERED_RECORDED,
) -> SourceVersions:
    return SourceVersions(
        dataset_version=str(raw_dataset["version"]),
        dataset_sha256=sha256(_DATASET_BYTES).hexdigest(),
        policy_version="PLUM_GHI_2024:1",
        policy_sha256=sha256(_POLICY_BYTES).hexdigest(),
        overlay_version="assignment-overlay:2",
        overlay_sha256=sha256(_OVERLAY_BYTES).hexdigest(),
        model_id=_MODEL_ID,
        prompt_versions=(
            "fast-triage-prompt-v1",
            "complex-extraction-prompt-v2",
        ),
        schema_versions=("triage-output-v2", "complex-extraction-v1"),
        graph_version=LangGraphClaimWorkflow.graph_version,
        execution_profile=profile,
        ocr_mode="ENABLED" if profile.uses_ocr else "BYPASSED",
    )


def _observation_id(document_version_id: UUID, role: DocumentRole) -> str:
    return sha256(f"{document_version_id}:{role.value}".encode()).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
