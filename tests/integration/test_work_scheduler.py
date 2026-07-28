import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select, update

from claims_backend.api.app import create_app
from claims_backend.application.work import LeaseLostError, WorkCompleted, WorkerService
from claims_backend.config import Settings
from claims_backend.domain.work import RetryDisposition, WorkRequest
from claims_backend.infrastructure.postgres.models import ClaimWorkItemRow
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler


@pytest.mark.asyncio
async def test_worker_leases_the_oldest_due_work_item(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await _submit_claim(client, "lease-oldest-due")

    scheduler = PostgresWorkScheduler(app.state.session_factory)
    leases = await scheduler.lease(
        worker_id="worker-1",
        limit=1,
        ttl=timedelta(minutes=5),
    )

    assert submitted.status_code == 202
    assert len(leases) == 1
    lease = leases[0]
    assert str(lease.claim_id) == submitted.json()["claim_id"]
    assert lease.operation_key == f"claim:{lease.claim_id}:process:v1"
    assert lease.worker_id == "worker-1"
    assert lease.attempt_number == 1
    assert lease.max_attempts == 3
    assert lease.lease_until > lease.leased_at
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_leasing_orders_due_work_and_ignores_future_work(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _submit_claim(client, "due-first")
        second = await _submit_claim(client, "due-second")
        future = await _submit_claim(client, "not-due")

    now = datetime.now(UTC)
    availability = {
        first.json()["claim_id"]: now - timedelta(minutes=1),
        second.json()["claim_id"]: now - timedelta(minutes=2),
        future.json()["claim_id"]: now + timedelta(minutes=1),
    }
    async with app.state.session_factory.begin() as session:
        for claim_id, available_at in availability.items():
            await session.execute(
                update(ClaimWorkItemRow)
                .where(ClaimWorkItemRow.claim_id == claim_id)
                .values(available_at=available_at)
            )

    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=lambda: now)
    leases = await scheduler.lease("ordering-worker", 10, timedelta(minutes=5))

    assert [str(lease.claim_id) for lease in leases] == [
        second.json()["claim_id"],
        first.json()["claim_id"],
    ]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_workers_never_lease_the_same_operation(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client, "concurrent-lease")

    now = datetime.now(UTC)

    async def lease(worker_id: str):
        scheduler = PostgresWorkScheduler(app.state.session_factory, clock=lambda: now)
        return await scheduler.lease(worker_id, 1, timedelta(minutes=5))

    batches = await asyncio.gather(*(lease(f"worker-{index}") for index in range(8)))
    leases = [item for batch in batches for item in batch]

    assert len(leases) == 1
    assert leases[0].attempt_number == 1
    async with app.state.session_factory() as session:
        row = await session.scalar(select(ClaimWorkItemRow))
    assert row is not None
    assert row.status == "LEASED"
    assert row.lease_token == leases[0].lease_token
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_with_a_new_fencing_token(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client, "expired-lease")

    clock = MutableClock(datetime.now(UTC))
    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=clock)
    original = (await scheduler.lease("crashed-worker", 1, timedelta(minutes=5)))[0]
    clock.advance(timedelta(minutes=6))
    reclaimed = (await scheduler.lease("recovery-worker", 1, timedelta(minutes=5)))[0]

    assert reclaimed.work_item_id == original.work_item_id
    assert reclaimed.lease_token != original.lease_token
    assert reclaimed.worker_id == "recovery-worker"
    assert reclaimed.attempt_number == 2
    with pytest.raises(LeaseLostError):
        await scheduler.complete(original)
    await scheduler.complete(reclaimed)

    async with app.state.session_factory() as session:
        row = await session.get(ClaimWorkItemRow, reclaimed.work_item_id)
    assert row is not None
    assert row.status == "COMPLETED"
    assert row.lease_owner is None
    assert row.lease_token is None
    assert row.lease_until is None
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_retry_is_durable_and_not_leaseable_until_its_due_time(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client, "durable-retry")

    clock = MutableClock(datetime.now(UTC))
    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=clock)
    first = (await scheduler.lease("retry-worker", 1, timedelta(minutes=5)))[0]
    retry_at = clock() + timedelta(minutes=10)
    disposition = await scheduler.retry(first, "PROVIDER_TIMEOUT", retry_at)

    assert disposition is RetryDisposition.SCHEDULED
    assert await scheduler.lease("early-worker", 1, timedelta(minutes=5)) == ()
    async with app.state.session_factory() as session:
        waiting = await session.get(ClaimWorkItemRow, first.work_item_id)
    assert waiting is not None
    assert waiting.status == "AVAILABLE"
    assert waiting.available_at == retry_at
    assert waiting.last_failure_code == "PROVIDER_TIMEOUT"
    assert waiting.lease_owner is None

    clock.advance(timedelta(minutes=10))
    second = (await scheduler.lease("retry-worker", 1, timedelta(minutes=5)))[0]
    assert second.attempt_number == 2
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_retry_budget_exhaustion_marks_work_failed(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client, "retry-exhaustion")

    async with app.state.session_factory.begin() as session:
        await session.execute(update(ClaimWorkItemRow).values(max_attempts=1))

    clock = MutableClock(datetime.now(UTC))
    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=clock)
    lease = (await scheduler.lease("last-attempt-worker", 1, timedelta(minutes=5)))[0]
    disposition = await scheduler.retry(
        lease,
        "PROVIDER_UNAVAILABLE",
        clock() + timedelta(minutes=1),
    )

    assert disposition is RetryDisposition.EXHAUSTED
    clock.advance(timedelta(minutes=2))
    assert await scheduler.lease("another-worker", 1, timedelta(minutes=5)) == ()
    async with app.state.session_factory() as session:
        failed = await session.get(ClaimWorkItemRow, lease.work_item_id)
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.last_failure_code == "PROVIDER_UNAVAILABLE"
    assert failed.attempt_count == failed.max_attempts == 1
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_worker_runs_handler_only_after_lease_transaction_commits(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _submit_claim(client, "committed-before-handler")

    clock = MutableClock(datetime.now(UTC))
    scheduler = PostgresWorkScheduler(app.state.session_factory, clock=clock)
    worker = WorkerService(scheduler)

    async def handler(lease):
        async with app.state.session_factory.begin() as session:
            visible = (
                await session.scalars(
                    select(ClaimWorkItemRow)
                    .where(ClaimWorkItemRow.id == lease.work_item_id)
                    .with_for_update(nowait=True)
                )
            ).one()
            assert visible.status == "LEASED"
            assert visible.lease_token == lease.lease_token
        return WorkCompleted()

    processed = await worker.run_once("boundary-worker", handler)

    assert processed is True
    async with app.state.session_factory() as session:
        completed = await session.scalar(select(ClaimWorkItemRow))
    assert completed is not None
    assert completed.status == "COMPLETED"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_enqueue_deduplicates_the_operation_key(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await _submit_claim(client, "claim-for-enqueue")

    now = datetime.now(UTC)
    claim_id = UUID(submitted.json()["claim_id"])
    request = WorkRequest(
        claim_id=claim_id,
        claim_version=1,
        operation_key=f"claim:{claim_id}:diagnostics:v1",
        available_at=now,
        max_attempts=3,
    )

    async def enqueue_once():
        scheduler = PostgresWorkScheduler(app.state.session_factory, clock=lambda: now)
        return await scheduler.enqueue(request)

    references = await asyncio.gather(*(enqueue_once() for _ in range(8)))

    assert sum(reference.created for reference in references) == 1
    assert len({reference.work_item_id for reference in references}) == 1
    async with app.state.session_factory() as session:
        work_count = len((await session.scalars(select(ClaimWorkItemRow))).all())
    assert work_count == 2
    await app.state.engine.dispose()


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self._value = value

    def __call__(self) -> datetime:
        return self._value

    def advance(self, duration: timedelta) -> None:
        self._value += duration


async def _submit_claim(client: AsyncClient, idempotency_key: str):
    return await client.post(
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
