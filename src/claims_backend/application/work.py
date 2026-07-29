import asyncio
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

    async def renew(self, lease: WorkLease, ttl: timedelta) -> WorkLease: ...

    async def retry(
        self,
        lease: WorkLease,
        failure_code: str,
        available_at: datetime,
    ) -> RetryDisposition: ...

    async def fail(self, lease: WorkLease, failure_code: str) -> None: ...


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
class WorkLeaseLost:
    """The handler lost execution ownership; the current owner must finish work."""


@dataclass(frozen=True, slots=True)
class WorkRetry:
    failure_code: str
    available_at: datetime


@dataclass(frozen=True, slots=True)
class WorkFailed:
    failure_code: str


type WorkOutcome = WorkCompleted | WorkCommitted | WorkLeaseLost | WorkRetry | WorkFailed
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
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(lease, heartbeat_stop))
        try:
            outcome = await handler(lease)
        finally:
            heartbeat_stop.set()
            await heartbeat
        if isinstance(outcome, WorkCompleted):
            await self._scheduler.complete(lease)
        elif isinstance(outcome, WorkLeaseLost):
            # A reclaimed lease belongs to another worker. Do not mutate its
            # work item or terminal claim state from this stale execution.
            pass
        elif isinstance(outcome, WorkRetry):
            await self._scheduler.retry(
                lease,
                outcome.failure_code,
                outcome.available_at,
            )
        elif isinstance(outcome, WorkFailed):
            await self._scheduler.fail(lease, outcome.failure_code)
        return True

    async def _heartbeat(self, lease: WorkLease, stop_event: asyncio.Event) -> None:
        interval = max(self._lease_ttl.total_seconds() / 3, 0.01)
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except TimeoutError:
                await self._scheduler.renew(lease, self._lease_ttl)
