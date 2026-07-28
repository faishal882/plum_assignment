import json
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from pypdf import PdfWriter
from sqlalchemy import select

from claims_backend.api.app import create_app
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.models import WorkflowRunRow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.observability import (
    ObservabilityConfig,
    create_observability,
    scan_telemetry_for_phi,
)


@pytest.mark.asyncio
async def test_workflow_has_one_correlated_trace_log_and_ordered_event_tree(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id = await _submit_claim(client, "observable-workflow")

    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(
            log_root=tmp_path / "logs",
            phi_canaries=("Kavita Nair", "Chronic Joint Pain"),
        ),
        process_name="worker",
        span_exporter=exporter,
    )
    scheduler = PostgresWorkScheduler(app.state.session_factory)
    repository = PostgresWorkflowRepository(app.state.session_factory)
    runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        repository,
        observability=observability,
    )
    await runtime.setup()

    assert await WorkerService(scheduler).run_once(
        "observable-worker",
        ClaimWorkflowProcessor(repository, runtime).process,
    )
    async with app.state.session_factory() as session:
        run_row = await session.scalar(
            select(WorkflowRunRow).where(WorkflowRunRow.claim_id == claim_id)
        )
    assert run_row is not None
    run = await repository.get_by_work_item(run_row.work_item_id)
    assert run is not None
    events = await repository.list_events(run.id)
    observability.shutdown()

    spans = exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "claim.workflow")
    nodes = [span for span in spans if span.name.startswith("claim.workflow.")]
    assert [span.attributes["node.name"] for span in nodes] == [
        "load_claim",
        "finalize",
    ]
    assert all(span.context.trace_id == root.context.trace_id for span in nodes)
    assert all(span.parent and span.parent.span_id == root.context.span_id for span in nodes)
    assert root.attributes["session.id"] == str(claim_id)
    assert root.attributes["workflow.execution_profile"] == "UNSPECIFIED"
    assert [
        (event.sequence, event.node_name, event.event_type, event.outcome) for event in events
    ] == [
        (1, "load_claim", "ENTRY", "RUNNING"),
        (2, "load_claim", "EXIT", "OK"),
        (3, "finalize", "ENTRY", "RUNNING"),
        (4, "finalize", "EXIT", "OK"),
    ]
    assert all(event.trace_id == f"{root.context.trace_id:032x}" for event in events)
    assert all(event.span_id for event in events)

    records = [
        json.loads(line) for line in (tmp_path / "logs" / "worker.jsonl").read_text().splitlines()
    ]
    assert {record["trace_id"] for record in records} == {f"{root.context.trace_id:032x}"}
    assert {record["process"] for record in records} == {"worker"}
    scan_telemetry_for_phi(
        [dict(span.attributes) for span in spans],
        phi_canaries=("Kavita Nair", "Chronic Joint Pain"),
    )
    scan_telemetry_for_phi(
        records,
        phi_canaries=("Kavita Nair", "Chronic Joint Pain"),
    )
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_api_process_writes_its_own_correlated_trace_and_log(
    migrated_database_url: str,
    tmp_path,
) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path / "logs"),
        process_name="api",
        span_exporter=exporter,
    )
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path),
        observability=observability,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/claims/00000000-0000-0000-0000-000000000099",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert response.status_code == 404
    observability.shutdown()
    span = exporter.get_finished_spans()[0]
    assert span.name == "api.request"
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/v1/claims/{claim_id}"
    assert span.attributes["http.response.status_code"] == 404
    record = json.loads((tmp_path / "logs" / "api.jsonl").read_text())
    assert record["process"] == "api"
    assert record["trace_id"] == f"{span.context.trace_id:032x}"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_submission_span_uses_claim_as_session_id(
    migrated_database_url: str,
    tmp_path,
) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path / "logs"),
        process_name="api",
        span_exporter=exporter,
    )
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path),
        observability=observability,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        claim_id = await _submit_claim(client, "submission-session")

    observability.shutdown()
    span = next(
        span for span in exporter.get_finished_spans() if span.name == "api.claim_submitted"
    )
    assert span.attributes["session.id"] == str(claim_id)
    assert span.attributes["claim.id"] == str(claim_id)
    await app.state.engine.dispose()


async def _submit_claim(client: AsyncClient, idempotency_key: str) -> UUID:
    response = await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp001",
            "Idempotency-Key": idempotency_key,
        },
        data={
            "metadata": json.dumps(
                {
                    "member_id": "EMP001",
                    "policy_id": "PLUM_GHI_2024",
                    "claim_category": "CONSULTATION",
                    "treatment_date": "2024-10-10",
                    "claimed_amount": "1000.00",
                    "currency": "INR",
                    "documents": [{"upload_index": 0, "client_document_id": "DOC-1"}],
                }
            )
        },
        files=[("files", ("claim.pdf", _pdf_bytes(), "application/pdf"))],
    )
    assert response.status_code == 202
    return UUID(response.json()["claim_id"])


def _pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()
