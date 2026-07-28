from datetime import timedelta
from io import BytesIO
import json

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.domain.workflow import ExecutionContract
from claims_backend.infrastructure.postgres.models import WorkflowRunRow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
    WorkflowRunConflictError,
)


@pytest.mark.asyncio
async def test_workflow_recovery_rejects_changed_execution_contract(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "execution-contract-claim",
            },
            data={
                "metadata": json.dumps(
                    {
                        "member_id": "EMP001",
                        "policy_id": "PLUM_GHI_2024",
                        "claim_category": "CONSULTATION",
                        "treatment_date": "2024-11-01",
                        "claimed_amount": "1500.00",
                        "currency": "INR",
                        "documents": [{"upload_index": 0, "client_document_id": "claim-document"}],
                    }
                )
            },
            files={"files": ("claim.pdf", _pdf_bytes(), "application/pdf")},
        )
    assert submitted.status_code == 202

    scheduler = PostgresWorkScheduler(app.state.session_factory)
    lease = (await scheduler.lease("contract-worker", 1, timedelta(minutes=5)))[0]
    repository = PostgresWorkflowRepository(app.state.session_factory)
    recorded = _contract(model_id="recorded-model-v1")
    workflow = await repository.get_or_create(
        lease,
        "claim-processing",
        "claim-processing-v7",
        recorded,
    )

    assert workflow.execution_contract == recorded
    async with app.state.session_factory() as session:
        stored = await session.scalar(
            select(WorkflowRunRow).where(WorkflowRunRow.id == workflow.id)
        )
    assert stored is not None
    assert stored.execution_contract == recorded.as_dict()

    with pytest.raises(WorkflowRunConflictError):
        await repository.get_or_create(
            lease,
            "claim-processing",
            "claim-processing-v7",
            _contract(model_id="changed-model-v2"),
        )
    await app.state.engine.dispose()


def _contract(*, model_id: str) -> ExecutionContract:
    return ExecutionContract(
        schema_version="execution-contract-v1",
        execution_profile="RECORDED_LOCAL",
        ocr_provider_name="RECORDED_DISCOVERY_OCR",
        ocr_provider_version="recorded-discovery-v1",
        model_provider_name="RECORDED_DOCUMENT_MODEL",
        model_provider_version="recorded-document-v1",
        model_routes=(
            (
                "FAST_TRIAGE",
                model_id,
                "ap-south-1",
                "fast-triage-prompt-v1",
                "triage-output-v2",
            ),
        ),
    )


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
