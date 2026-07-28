from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from claims_backend.domain.work import RetryDisposition, WorkLease, WorkRef, WorkRequest


class WorkScheduler(Protocol):
    async def enqueue(self, request: WorkRequest) -> WorkRef: ...

    async def lease(
        self,
        worker_id: str,
        limit: int,
        ttl: timedelta,
    ) -> tuple[WorkLease, ...]: ...

    async def complete(self, lease: WorkLease) -> None: ...

    async def retry(
        self,
        lease: WorkLease,
        failure_code: str,
        available_at: datetime,
    ) -> RetryDisposition: ...


class LeaseLostError(Exception):
    pass


class InvalidWorkRequestError(ValueError):
    pass


class OperationKeyConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WorkCompleted:
    pass


@dataclass(frozen=True, slots=True)
class WorkCommitted:
    """The handler atomically completed the leased work item."""


@dataclass(frozen=True, slots=True)
class WorkRetry:
    failure_code: str
    available_at: datetime


type WorkOutcome = WorkCompleted | WorkCommitted | WorkRetry
type WorkHandler = Callable[[WorkLease], Awaitable[WorkOutcome]]


class WorkerService:
    def __init__(
        self,
        scheduler: WorkScheduler,
        lease_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        self._scheduler = scheduler
        self._lease_ttl = lease_ttl

    async def run_once(self, worker_id: str, handler: WorkHandler) -> bool:
        leases = await self._scheduler.lease(worker_id, limit=1, ttl=self._lease_ttl)
        if not leases:
            return False

        lease = leases[0]
        outcome = await handler(lease)
        if isinstance(outcome, WorkCompleted):
            await self._scheduler.complete(lease)
        elif isinstance(outcome, WorkRetry):
            await self._scheduler.retry(
                lease,
                outcome.failure_code,
                outcome.available_at,
            )
        return True
