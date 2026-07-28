from typing import Protocol
from uuid import UUID

from claims_backend.application.work import WorkCommitted, WorkCompleted
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import WorkflowEffect, WorkflowRun, WorkflowRunStatus


class WorkflowRepository(Protocol):
    async def get_or_create(
        self,
        lease: WorkLease,
        graph_name: str,
        graph_version: str,
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


class WorkflowRuntime(Protocol):
    graph_name: str
    graph_version: str

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
    ) -> None:
        self._repository = repository
        self._runtime = runtime

    async def process(self, lease: WorkLease) -> WorkCompleted | WorkCommitted:
        workflow_run = await self._repository.get_or_create(
            lease,
            self._runtime.graph_name,
            self._runtime.graph_version,
        )
        if workflow_run.status is WorkflowRunStatus.COMPLETED:
            return WorkCompleted()

        resume = workflow_run.status is WorkflowRunStatus.RUNNING
        workflow_run = await self._repository.mark_running(workflow_run.id)
        work_committed = await self._runtime.run(workflow_run, lease, resume=resume)
        if work_committed:
            return WorkCommitted()
        await self._repository.mark_completed(workflow_run.id)
        return WorkCompleted()
