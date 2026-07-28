import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.work import (
    InvalidWorkRequestError,
    LeaseLostError,
    OperationKeyConflictError,
    WorkScheduler,
)
from claims_backend.domain.work import (
    RetryDisposition,
    WorkLease,
    WorkRef,
    WorkRequest,
    WorkStatus,
)
from claims_backend.infrastructure.postgres.models import ClaimWorkItemRow

_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class PostgresWorkScheduler(WorkScheduler):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def enqueue(self, request: WorkRequest) -> WorkRef:
        _validate_operation_key(request.operation_key)
        available_at = _aware_utc(request.available_at)
        if request.claim_version <= 0:
            raise InvalidWorkRequestError("Claim version must be positive.")
        if request.max_attempts <= 0:
            raise InvalidWorkRequestError("Maximum attempts must be positive.")
        now = _aware_utc(self._clock())
        work_item_id = uuid4()

        async with self._session_factory.begin() as session:
            inserted_id = await session.scalar(
                insert(ClaimWorkItemRow)
                .values(
                    id=work_item_id,
                    claim_id=request.claim_id,
                    claim_version=request.claim_version,
                    operation_key=request.operation_key,
                    status=WorkStatus.AVAILABLE.value,
                    available_at=available_at,
                    attempt_count=0,
                    max_attempts=request.max_attempts,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=[ClaimWorkItemRow.operation_key])
                .returning(ClaimWorkItemRow.id)
            )
            if inserted_id is not None:
                return WorkRef(
                    work_item_id=inserted_id,
                    claim_id=request.claim_id,
                    operation_key=request.operation_key,
                    created=True,
                )
            existing = (
                await session.scalars(
                    select(ClaimWorkItemRow).where(
                        ClaimWorkItemRow.operation_key == request.operation_key
                    )
                )
            ).one()
            if (
                existing.claim_id != request.claim_id
                or existing.claim_version != request.claim_version
                or existing.max_attempts != request.max_attempts
            ):
                raise OperationKeyConflictError
            return WorkRef(
                work_item_id=existing.id,
                claim_id=existing.claim_id,
                operation_key=existing.operation_key,
                created=False,
            )

    async def lease(
        self,
        worker_id: str,
        limit: int,
        ttl: timedelta,
    ) -> tuple[WorkLease, ...]:
        _validate_lease_request(worker_id, limit, ttl)
        now = _aware_utc(self._clock())
        lease_until = now + ttl
        leases: list[WorkLease] = []

        async with self._session_factory.begin() as session:
            await session.execute(
                update(ClaimWorkItemRow)
                .where(
                    ClaimWorkItemRow.status == WorkStatus.LEASED.value,
                    ClaimWorkItemRow.lease_until <= now,
                    ClaimWorkItemRow.attempt_count >= ClaimWorkItemRow.max_attempts,
                )
                .values(
                    status=WorkStatus.FAILED.value,
                    lease_owner=None,
                    lease_token=None,
                    lease_until=None,
                    last_failure_code="ATTEMPTS_EXHAUSTED",
                    updated_at=now,
                )
            )
            eligible = or_(
                and_(
                    ClaimWorkItemRow.status == WorkStatus.AVAILABLE.value,
                    ClaimWorkItemRow.available_at <= now,
                ),
                and_(
                    ClaimWorkItemRow.status == WorkStatus.LEASED.value,
                    ClaimWorkItemRow.lease_until <= now,
                ),
            )
            rows = (
                await session.scalars(
                    select(ClaimWorkItemRow)
                    .where(
                        eligible,
                        ClaimWorkItemRow.attempt_count < ClaimWorkItemRow.max_attempts,
                    )
                    .order_by(
                        ClaimWorkItemRow.available_at,
                        ClaimWorkItemRow.created_at,
                        ClaimWorkItemRow.id,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                lease_token = uuid4()
                row.status = WorkStatus.LEASED.value
                row.lease_owner = worker_id
                row.lease_token = lease_token
                row.lease_until = lease_until
                row.attempt_count += 1
                row.updated_at = now
                leases.append(
                    WorkLease(
                        work_item_id=row.id,
                        claim_id=row.claim_id,
                        claim_version=row.claim_version,
                        operation_key=row.operation_key,
                        worker_id=worker_id,
                        lease_token=lease_token,
                        leased_at=now,
                        lease_until=lease_until,
                        available_at=row.available_at,
                        attempt_number=row.attempt_count,
                        max_attempts=row.max_attempts,
                    )
                )

        return tuple(leases)

    async def complete(self, lease: WorkLease) -> None:
        now = _aware_utc(self._clock())
        async with self._session_factory.begin() as session:
            completed_id = await session.scalar(
                update(ClaimWorkItemRow)
                .where(
                    ClaimWorkItemRow.id == lease.work_item_id,
                    ClaimWorkItemRow.status == WorkStatus.LEASED.value,
                    ClaimWorkItemRow.lease_owner == lease.worker_id,
                    ClaimWorkItemRow.lease_token == lease.lease_token,
                    ClaimWorkItemRow.lease_until == lease.lease_until,
                    ClaimWorkItemRow.lease_until > now,
                )
                .values(
                    status=WorkStatus.COMPLETED.value,
                    lease_owner=None,
                    lease_token=None,
                    lease_until=None,
                    updated_at=now,
                )
                .returning(ClaimWorkItemRow.id)
            )
            if completed_id is None:
                raise LeaseLostError

    async def retry(
        self,
        lease: WorkLease,
        failure_code: str,
        available_at: datetime,
    ) -> RetryDisposition:
        _validate_failure_code(failure_code)
        now = _aware_utc(self._clock())
        retry_at = _aware_utc(available_at)
        if retry_at <= now:
            raise InvalidWorkRequestError("Retry availability must be in the future.")

        async with self._session_factory.begin() as session:
            row = (
                await session.scalars(
                    select(ClaimWorkItemRow)
                    .where(
                        ClaimWorkItemRow.id == lease.work_item_id,
                        ClaimWorkItemRow.status == WorkStatus.LEASED.value,
                        ClaimWorkItemRow.lease_owner == lease.worker_id,
                        ClaimWorkItemRow.lease_token == lease.lease_token,
                        ClaimWorkItemRow.lease_until == lease.lease_until,
                        ClaimWorkItemRow.lease_until > now,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise LeaseLostError
            row.lease_owner = None
            row.lease_token = None
            row.lease_until = None
            row.last_failure_code = failure_code
            row.updated_at = now
            if row.attempt_count >= row.max_attempts:
                row.status = WorkStatus.FAILED.value
                return RetryDisposition.EXHAUSTED
            row.status = WorkStatus.AVAILABLE.value
            row.available_at = retry_at
            return RetryDisposition.SCHEDULED


def _validate_lease_request(worker_id: str, limit: int, ttl: timedelta) -> None:
    if _WORKER_ID_PATTERN.fullmatch(worker_id) is None:
        raise InvalidWorkRequestError("Worker ID is invalid.")
    if not 1 <= limit <= 100:
        raise InvalidWorkRequestError("Lease limit must be between 1 and 100.")
    if ttl <= timedelta(0):
        raise InvalidWorkRequestError("Lease TTL must be positive.")


def _validate_failure_code(failure_code: str) -> None:
    if _FAILURE_CODE_PATTERN.fullmatch(failure_code) is None:
        raise InvalidWorkRequestError("Failure code is invalid.")


def _validate_operation_key(operation_key: str) -> None:
    if not operation_key or len(operation_key) > 160:
        raise InvalidWorkRequestError("Operation key must contain between 1 and 160 characters.")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidWorkRequestError("Scheduler timestamps must be timezone-aware.")
    return value.astimezone(UTC)
