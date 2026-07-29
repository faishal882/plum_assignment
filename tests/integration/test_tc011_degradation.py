import json
import shutil
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.fixtures.failures import (
    EvaluationAnomalyFailureInjector,
)
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimRow,
    ComponentFailureRow,
    DecisionRecordRow,
)
from claims_backend.infrastructure.postgres.reconstruction import (
    PostgresClaimReconstructor,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.observability import ObservabilityConfig, create_observability

_POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()


@pytest.mark.asyncio
async def test_tc011_degrades_only_anomaly_enrichment_without_losing_decision(
    migrated_database_url: str,
    tmp_path,
) -> None:
    fixture_engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(fixture_engine, expire_on_commit=False)
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-10-28",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP006",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "0.00",
                        "currency": "INR",
                        "as_of_date": "2024-10-28",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc011-member-facts.json",
    )
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    sink = _FailingEngineeringSink()
    exporter = InMemorySpanExporter()
    log_root = tmp_path / "diagnostics"
    observability = create_observability(
        ObservabilityConfig(log_root=log_root),
        process_name="worker",
        span_exporter=exporter,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rejected_injection = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp006",
                "Idempotency-Key": "tc011-production-injection",
            },
            data={"metadata": json.dumps({**_metadata(), "simulate_component_failure": True})},
            files=_files(),
        )
        assert rejected_injection.status_code == 422
        assert rejected_injection.json()["error"]["code"] == "INVALID_CLAIM_METADATA"

        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp006",
                "Idempotency-Key": "tc011-degradation",
            },
            data={"metadata": json.dumps(_metadata())},
            files=_files(),
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])

        await StructuredComponentFixtureAdapter(factory).seed_tc011(claim_id, 1)
        scheduler = PostgresWorkScheduler(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(
            app.state.session_factory,
            anomaly_enricher=EvaluationAnomalyFailureInjector(),
            engineering_events=sink,
        )
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
            observability=observability,
        )
        await runtime.setup()

        assert await WorkerService(scheduler).run_once(
            "tc011-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp006"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "DECIDED"
    assert body["adjudication"] == {
        "recommendation": "APPROVED",
        "approved_amount": "4000.00",
        "currency": "INR",
    }
    assert body["handling_status"] == "MANUAL_REVIEW_RECOMMENDED"
    quality = body["processing_quality"]
    assert quality["completeness"] < 1
    assert quality["confidence"] < 1
    assert quality["degraded_components"] == [
        {
            "component": "ANOMALY_ENRICHMENT",
            "criticality": "NONCRITICAL",
            "attempts": 1,
            "failure_code": "ANOMALY_ENRICHMENT_UNAVAILABLE",
            "retryable": False,
            "effect_on_handling": "MANUAL_REVIEW_RECOMMENDED",
        }
    ]
    assert sink.attempts == 1
    reconstructor = PostgresClaimReconstructor(app.state.session_factory)
    reconstruction = await reconstructor.reconstruct(claim_id)
    assert reconstruction is not None
    assert reconstruction.decision is not None
    assert reconstruction.decision["recommendation"] == "APPROVED"
    assert reconstruction.decision["approved_paise"] == 400_000
    assert reconstruction.component_failures[0]["component"] == "ANOMALY_ENRICHMENT"
    assert reconstruction.evidence_references
    before_diagnostic_deletion = reconstruction.canonical_sha256
    observability.shutdown()
    exporter.clear()
    shutil.rmtree(log_root)
    reconstructed_without_diagnostics = await reconstructor.reconstruct(claim_id)
    assert reconstructed_without_diagnostics is not None
    assert reconstructed_without_diagnostics.canonical_sha256 == before_diagnostic_deletion

    async with app.state.session_factory() as session:
        claim = await session.get(ClaimRow, claim_id)
        decision = await session.scalar(
            select(DecisionRecordRow).where(DecisionRecordRow.claim_id == claim_id)
        )
        failure = await session.scalar(
            select(ComponentFailureRow).where(ComponentFailureRow.claim_id == claim_id)
        )
        audit = await session.scalar(
            select(AuditEventRow).where(
                AuditEventRow.claim_id == claim_id,
                AuditEventRow.event_type == "CLAIM_DECIDED",
            )
        )

    assert claim is not None
    assert claim.review_task_id is None
    assert decision is not None
    assert decision.recommendation == "APPROVED"
    assert decision.approved_paise == 400_000
    assert failure is not None
    assert failure.component == "ANOMALY_ENRICHMENT"
    assert failure.attempts == 1
    assert failure.failure_code == "ANOMALY_ENRICHMENT_UNAVAILABLE"
    assert audit is not None
    assert audit.payload["processing_quality"] == quality
    await fixture_engine.dispose()
    await app.state.engine.dispose()


class _FailingEngineeringSink:
    def __init__(self) -> None:
        self.attempts = 0

    async def emit(self, event: dict[str, object]) -> None:
        self.attempts += 1
        raise OSError("injected engineering log failure")


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP006",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "ALTERNATIVE_MEDICINE",
        "treatment_date": "2024-10-28",
        "claimed_amount": "4000.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F021"},
            {"upload_index": 1, "client_document_id": "F022"},
        ],
    }


def _files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", ("prescription.pdf", _pdf_bytes(), "application/pdf")),
        ("files", ("hospital-bill.pdf", _pdf_bytes(), "application/pdf")),
    ]


def _pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()
