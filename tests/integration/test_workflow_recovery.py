import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import text

from claims_backend.api.app import create_app
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.workflow import WorkflowRunStatus
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)


class ControlledCrash(RuntimeError):
    pass


class CrashBeforeFinalize:
    def __init__(self) -> None:
        self.entries: list[str] = []

    async def __call__(self, node_name: str) -> None:
        self.entries.append(node_name)
        if node_name == "finalize":
            raise ControlledCrash


class RecordEntries:
    def __init__(self) -> None:
        self.entries: list[str] = []

    async def __call__(self, node_name: str) -> None:
        self.entries.append(node_name)


class CrashAfterLoadEffect:
    async def __call__(self, node_name: str) -> None:
        if node_name == "load_claim":
            raise ControlledCrash


@pytest.mark.asyncio
async def test_expired_worker_resumes_from_committed_postgres_checkpoint(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await _submit_claim(client)

    clock = MutableClock(datetime.now(UTC))
    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=clock)
    first_lease = (await scheduler.lease("crashing-worker", 1, timedelta(minutes=5)))[0]
    repository = PostgresWorkflowRepository(app.state.session_factory)
    crash_hook = CrashBeforeFinalize()
    first_runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        repository,
        before_node=crash_hook,
    )
    await first_runtime.setup()
    first_processor = ClaimWorkflowProcessor(repository, first_runtime)

    with pytest.raises(ControlledCrash):
        await first_processor.process(first_lease)

    interrupted = await repository.get_by_work_item(first_lease.work_item_id)
    assert interrupted is not None
    assert interrupted.status is WorkflowRunStatus.RUNNING
    assert crash_hook.entries == ["load_claim", "finalize"]

    clock.advance(timedelta(minutes=6))
    recovery_lease = (await scheduler.lease("recovery-worker", 1, timedelta(minutes=5)))[0]
    recovery_hook = RecordEntries()
    recovery_runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        repository,
        before_node=recovery_hook,
    )
    recovery_processor = ClaimWorkflowProcessor(repository, recovery_runtime)
    await recovery_processor.process(recovery_lease)
    await scheduler.complete(recovery_lease)

    completed = await repository.get_by_work_item(first_lease.work_item_id)
    assert completed is not None
    assert completed.id == interrupted.id
    assert completed.status is WorkflowRunStatus.COMPLETED
    assert str(completed.claim_id) == submitted.json()["claim_id"]
    assert completed.claim_version == 1
    assert recovery_hook.entries == ["finalize"]

    effects = await repository.list_effects(completed.id)
    assert [effect.effect_key for effect in effects] == [
        "claim-loaded:v1",
        "skeleton-completed:v1",
    ]
    async with app.state.session_factory() as session:
        checkpoint_threads = (
            await session.execute(
                text("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": str(completed.id)},
            )
        ).scalars()
    assert checkpoint_threads.all() == [str(completed.id)]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_reexecuted_node_does_not_duplicate_its_committed_effect(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client)

    scheduler = PostgresWorkScheduler(app.state.session_factory)
    lease = (await scheduler.lease("effect-crash-worker", 1, timedelta(minutes=5)))[0]
    repository = PostgresWorkflowRepository(app.state.session_factory)
    crashing_runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        repository,
        after_effect=CrashAfterLoadEffect(),
    )
    await crashing_runtime.setup()
    crashing_processor = ClaimWorkflowProcessor(repository, crashing_runtime)

    with pytest.raises(ControlledCrash):
        await crashing_processor.process(lease)

    interrupted = await repository.get_by_work_item(lease.work_item_id)
    assert interrupted is not None
    interrupted_effects = await repository.list_effects(interrupted.id)
    assert [effect.effect_key for effect in interrupted_effects] == ["claim-loaded:v1"]

    recovery_hook = RecordEntries()
    recovery_runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        repository,
        before_node=recovery_hook,
    )
    recovery_processor = ClaimWorkflowProcessor(repository, recovery_runtime)
    await recovery_processor.process(lease)
    await recovery_processor.process(lease)
    await scheduler.complete(lease)

    effects = await repository.list_effects(interrupted.id)
    assert [effect.effect_key for effect in effects] == [
        "claim-loaded:v1",
        "skeleton-completed:v1",
    ]
    assert recovery_hook.entries == ["load_claim", "finalize"]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_worker_service_completes_one_workflow_run_and_work_item(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client)

    scheduler = PostgresWorkScheduler(app.state.session_factory)
    repository = PostgresWorkflowRepository(app.state.session_factory)
    runtime = LangGraphClaimWorkflow(migrated_database_url, repository)
    await runtime.setup()
    processor = ClaimWorkflowProcessor(repository, runtime)
    worker = WorkerService(scheduler)

    processed = await worker.run_once("workflow-worker", processor.process)
    no_more_work = await worker.run_once("workflow-worker", processor.process)

    assert processed is True
    assert no_more_work is False
    async with app.state.session_factory() as session:
        run_status = await session.scalar(text("SELECT status FROM workflow_runs"))
        work_status = await session.scalar(text("SELECT status FROM claim_work_items"))
        run_count = await session.scalar(text("SELECT count(*) FROM workflow_runs"))
    assert run_status == "COMPLETED"
    assert work_status == "COMPLETED"
    assert run_count == 1
    await app.state.engine.dispose()


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def __call__(self) -> datetime:
        return self._value

    def advance(self, duration: timedelta) -> None:
        self._value += duration


async def _submit_claim(client: AsyncClient):
    return await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp001",
            "Idempotency-Key": "workflow-recovery-claim",
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
                    "documents": [
                        {
                            "upload_index": 0,
                            "client_document_id": "doc-prescription",
                        }
                    ],
                }
            )
        },
        files={"files": ("prescription.pdf", _pdf_bytes(), "application/pdf")},
    )


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
