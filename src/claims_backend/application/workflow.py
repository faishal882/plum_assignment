from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from claims_backend.application.failure_policy import (
    RetrySchedule,
    classify_processing_failure,
)
from claims_backend.application.work import WorkCommitted, WorkCompleted, WorkFailed, WorkRetry
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import (
    ExecutionContract,
    NewWorkflowEvent,
    WorkflowEffect,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)


class WorkflowRepository(Protocol):
    async def get_or_create(
        self,
        lease: WorkLease,
        graph_name: str,
        graph_version: str,
        execution_contract: ExecutionContract,
    ) -> WorkflowRun: ...

    async def get_by_work_item(self, work_item_id: UUID) -> WorkflowRun | None: ...

    async def mark_running(self, workflow_run_id: UUID) -> WorkflowRun: ...

    async def mark_completed(self, workflow_run_id: UUID) -> WorkflowRun: ...

    async def record_effect(
        self,
        workflow_run_id: UUID,
        effect_key: str,
        effect_type: str,
        payload: dict[str, object],
    ) -> bool: ...

    async def list_effects(self, workflow_run_id: UUID) -> tuple[WorkflowEffect, ...]: ...

    async def record_event(
        self,
        workflow_run_id: UUID,
        event: NewWorkflowEvent,
    ) -> WorkflowEvent: ...

    async def list_events(self, workflow_run_id: UUID) -> tuple[WorkflowEvent, ...]: ...


class WorkflowRuntime(Protocol):
    graph_name: str
    graph_version: str
    execution_contract: ExecutionContract

    async def setup(self) -> None: ...

    async def run(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        *,
        resume: bool,
    ) -> bool: ...


class ClaimWorkflowProcessor:
    def __init__(
        self,
        repository: WorkflowRepository,
        runtime: WorkflowRuntime,
        *,
        retry_schedule: RetrySchedule | None = None,
        runtime_resolver: Callable[[WorkflowRun | None], Awaitable[WorkflowRuntime]] | None = None,
    ) -> None:
        self._repository = repository
        self._runtime = runtime
        self._retry_schedule = retry_schedule or RetrySchedule()
        self._runtime_resolver = runtime_resolver

    async def setup(self) -> None:
        """Initialize durable workflow state before the worker leases work."""
        await self._runtime.setup()

    async def process(
        self,
        lease: WorkLease,
    ) -> WorkCompleted | WorkCommitted | WorkRetry | WorkFailed:
        if self._runtime_resolver is None:
            runtime = self._runtime
        else:
            existing = await self._repository.get_by_work_item(lease.work_item_id)
            runtime = await self._runtime_resolver(existing)
        workflow_run = await self._repository.get_or_create(
            lease,
            runtime.graph_name,
            runtime.graph_version,
            runtime.execution_contract,
        )
        if workflow_run.status is WorkflowRunStatus.COMPLETED:
            return WorkCompleted()

        resume = workflow_run.status is WorkflowRunStatus.RUNNING
        workflow_run = await self._repository.mark_running(workflow_run.id)
        try:
            work_committed = await runtime.run(workflow_run, lease, resume=resume)
        except Exception as error:
            failure = classify_processing_failure(error)
            if failure is None:
                raise
            if failure.retryable:
                return WorkRetry(
                    failure_code=failure.code,
                    available_at=self._retry_schedule.available_at(
                        attempt_number=lease.attempt_number
                    ),
                )
            return WorkFailed(failure_code=failure.code)
        if work_committed:
            return WorkCommitted()
        await self._repository.mark_completed(workflow_run.id)
        return WorkCompleted()
