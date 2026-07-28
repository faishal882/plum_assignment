import json
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from claims_backend.api.app import create_app
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    CasefileRow,
    DecisionRecordRow,
    DocumentTriageResultRow,
    ProcessingFixtureRow,
    RuleResultRow,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.worker.application import create_claim_worker


@pytest.mark.asyncio
async def test_tc001_stops_after_two_prescriptions_and_requests_hospital_bill(
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
                "Idempotency-Key": "tc001-role-gate",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("first.jpg", _jpeg_bytes(), "image/jpeg")),
                ("files", ("second.jpg", _jpeg_bytes(), "image/jpeg")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(app.state.session_factory).seed_tc001_triage(
            claim_id, 1
        )

        scheduler = PostgresWorkScheduler(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(scheduler).run_once(
            "tc001-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "ACTION_REQUIRED"
    assert "adjudication" not in body
    assert "explanation" not in body
    assert body["action"] == {
        "code": "MISSING_REQUIRED_DOCUMENT",
        "message": ("You uploaded two prescriptions. Please upload the required hospital bill."),
        "observed_document_roles": ["PRESCRIPTION", "PRESCRIPTION"],
        "required_document_roles": ["HOSPITAL_BILL"],
    }

    async with app.state.session_factory() as session:
        triage = (
            await session.scalars(
                select(DocumentTriageResultRow).order_by(DocumentTriageResultRow.client_document_id)
            )
        ).all()
        assert [(item.role, item.readability) for item in triage] == [
            ("PRESCRIPTION", "READABLE"),
            ("PRESCRIPTION", "READABLE"),
        ]
        assert await session.scalar(select(func.count()).select_from(CasefileRow)) == 0
        assert await session.scalar(select(func.count()).select_from(DecisionRecordRow)) == 0
        assert await session.scalar(select(func.count()).select_from(RuleResultRow)) == 0

    workflow_run = await workflows.get_by_work_item(await _work_item_id(app))
    assert workflow_run is not None
    effects = await workflows.list_effects(workflow_run.id)
    assert [effect.effect_type for effect in effects] == [
        "CLAIM_VERSION_LOADED",
        "LOCAL_MEDIA_INSPECTED",
        "DOCUMENT_TRIAGE_COMPLETED",
        "MEMBER_ACTION_COMMITTED",
    ]
    assert not {
        "TEXTRACT_STARTED",
        "EXTRACTION_STARTED",
        "CASEFILE_FROZEN",
        "ADJUDICATION_PROPOSED",
        "DECISION_COMMITTED",
    } & {effect.effect_type for effect in effects}

    for table_name in ("document_triage_results", "member_actions"):
        with pytest.raises(DBAPIError):
            async with app.state.session_factory.begin() as session:
                await session.execute(
                    text(f"DELETE FROM {table_name} WHERE claim_id = :claim_id"),
                    {"claim_id": claim_id},
                )

    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_public_claim_processes_without_processing_fixture_seed(
    migrated_database_url: str,
    tmp_path,
) -> None:
    settings = Settings(
        database_url=migrated_database_url,
        data_root=tmp_path / "documents",
        log_root=tmp_path / "logs",
        observability_enabled=True,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "public-no-fixture-tc001",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("first.jpg", _jpeg_bytes(), "image/jpeg")),
                ("files", ("second.jpg", _jpeg_bytes(), "image/jpeg")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])

        async with app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(ProcessingFixtureRow)) == 0

        runtime = create_process_runtime(settings, process_name="worker")
        worker = create_claim_worker(runtime)
        try:
            await worker.setup()
            assert await worker.run_once()
        finally:
            await worker.close()

        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert projection.status_code == 200
    assert projection.json()["lifecycle_status"] == "ACTION_REQUIRED"
    assert projection.json()["action"]["code"] == "MISSING_REQUIRED_DOCUMENT"
    assert (tmp_path / "logs" / "worker.jsonl").exists()
    assert (tmp_path / "logs" / "worker.jsonl").read_text().strip()

    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingFixtureRow)) == 0
        assert await session.scalar(select(func.count()).select_from(DocumentTriageResultRow)) == 2
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
            {"upload_index": 0, "client_document_id": "F001"},
            {"upload_index": 1, "client_document_id": "F002"},
        ],
    }


def _jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="JPEG")
    return output.getvalue()
