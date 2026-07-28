import asyncio
import json
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from claims_backend.api.app import create_app
from claims_backend.application.setup_import import SetupDataApplication
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
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.worker.application import create_claim_worker

_POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()


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


@pytest.mark.asyncio
async def test_public_claim_decides_without_processing_fixture_seed(
    migrated_database_url: str,
    tmp_path,
) -> None:
    settings = Settings(database_url=migrated_database_url, data_root=tmp_path / "documents")
    app = create_app(settings)
    await _import_decision_utilization(app.state.session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "public-no-fixture-decision",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.jpg", _jpeg_bytes(), "image/jpeg")),
                ("files", ("bill.jpg", _bill_jpeg_bytes(), "image/jpeg")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
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
    assert projection.json()["lifecycle_status"] == "DECIDED"
    assert projection.json()["adjudication"]["approved_amount"] == "1350.00"
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingFixtureRow)) == 0
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_assignment_tc004_documents_process_without_fixture_seed(
    migrated_database_url: str,
    tmp_path,
) -> None:
    settings = Settings(database_url=migrated_database_url, data_root=tmp_path / "documents")
    app = create_app(settings)
    await _import_decision_utilization(app.state.session_factory)
    prescription, bill = _assignment_tc004_documents()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "assignment-tc004-no-fixture",
            },
            data={"metadata": json.dumps(_assignment_tc004_metadata())},
            files=[
                ("files", ("prescription.jpg", prescription, "image/jpeg")),
                ("files", ("bill.jpg", bill, "image/jpeg")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        worker = create_claim_worker(create_process_runtime(settings, process_name="worker"))
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
    assert projection.json()["lifecycle_status"] == "DECIDED"
    assert projection.json()["adjudication"]["approved_amount"] == "1350.00"
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingFixtureRow)) == 0
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_worker_loop_processes_claim_submitted_after_startup(
    migrated_database_url: str,
    tmp_path,
) -> None:
    settings = Settings(
        database_url=migrated_database_url,
        data_root=tmp_path / "documents",
        worker_poll_seconds=1,
    )
    app = create_app(settings)
    runtime = create_process_runtime(settings, process_name="worker")
    worker = create_claim_worker(runtime)
    stop_event = asyncio.Event()
    await worker.setup()
    worker_task = asyncio.create_task(worker.run_loop(stop_event))
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health/live")).json() == {"status": "ok"}
            assert (await client.get("/health/ready")).json() == {"status": "ok"}
            submitted = await client.post(
                "/v1/claims",
                headers={
                    "X-Dev-Username": "member.emp001",
                    "Idempotency-Key": "worker-loop-tc001",
                },
                data={"metadata": json.dumps(_metadata())},
                files=[
                    ("files", ("first.jpg", _jpeg_bytes(), "image/jpeg")),
                    ("files", ("second.jpg", _jpeg_bytes(), "image/jpeg")),
                ],
            )
            claim_id = UUID(submitted.json()["claim_id"])
            lifecycle = "QUEUED"
            for _ in range(30):
                await asyncio.sleep(0.1)
                projection = await client.get(
                    f"/v1/claims/{claim_id}",
                    headers={"X-Dev-Username": "member.emp001"},
                )
                lifecycle = projection.json()["lifecycle_status"]
                if lifecycle != "QUEUED":
                    break
            assert lifecycle == "ACTION_REQUIRED"
    finally:
        stop_event.set()
        await asyncio.wait_for(worker_task, timeout=2)
        await worker.close()
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


def _bill_jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 64), (30, 90, 180)).save(output, format="JPEG")
    return output.getvalue()


def _assignment_tc004_metadata() -> dict[str, object]:
    return {
        **_metadata(),
        "documents": [
            {"upload_index": 0, "client_document_id": "F007"},
            {"upload_index": 1, "client_document_id": "F008"},
        ],
    }


def _assignment_tc004_documents() -> tuple[bytes, bytes]:
    prescription = _assignment_document_image(
        "PRESCRIPTION\n"
        + json.dumps(
            {
                "date": "2024-11-01",
                "diagnosis": "Viral Fever",
                "doctor_name": "Dr. Arun Sharma",
                "doctor_registration": "KA/45678/2015",
                "medicines": ["Paracetamol 650mg", "Vitamin C 500mg"],
                "patient_name": "Rajesh Kumar",
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
    )
    bill = _assignment_document_image(
        "HOSPITAL_BILL\n"
        + json.dumps(
            {
                "date": "2024-11-01",
                "hospital_name": "City Clinic, Bengaluru",
                "line_items": [
                    {"amount": 1000, "description": "Consultation Fee"},
                    {"amount": 300, "description": "CBC Test"},
                    {"amount": 200, "description": "Dengue NS1 Test"},
                ],
                "patient_name": "Rajesh Kumar",
                "total": 1500,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
    )
    return prescription, bill


def _assignment_document_image(text: str) -> bytes:
    image = Image.new("RGB", (1400, 1000), "white")
    ImageDraw.Draw(image).multiline_text((80, 80), text, fill="black", spacing=14)
    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=False, progressive=False)
    return output.getvalue()


async def _import_decision_utilization(factory) -> None:
    member_data = json.dumps(
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
    ).encode()
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=member_data,
        member_data_source_name="recorded-decision-member-facts.json",
    )
