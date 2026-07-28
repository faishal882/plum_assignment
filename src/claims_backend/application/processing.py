from typing import Protocol
from uuid import UUID

from claims_backend.domain.processing import (
    CasefilePreparationResult,
    EarlyGateResult,
    FrozenCasefileRef,
    PagePreparationResult,
    ProcessingRoute,
)
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import WorkflowRun


class ClaimProcessor(Protocol):
    async def route(self, workflow_run: WorkflowRun) -> ProcessingRoute: ...

    async def inspect_media(self, workflow_run: WorkflowRun) -> dict[str, object]: ...

    async def freeze_casefile(
        self,
        workflow_run: WorkflowRun,
    ) -> FrozenCasefileRef: ...

    async def reconcile_casefile(
        self,
        workflow_run: WorkflowRun,
    ) -> CasefilePreparationResult: ...

    async def evaluate_casefile(self, casefile_id: UUID) -> str: ...

    async def commit_decision(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        casefile_id: UUID,
    ) -> None: ...

    async def triage_documents(
        self,
        workflow_run: WorkflowRun,
    ) -> EarlyGateResult: ...

    async def commit_member_action(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        result: EarlyGateResult,
    ) -> None: ...

    async def render_documents(
        self,
        workflow_run: WorkflowRun,
    ) -> PagePreparationResult: ...

    async def ocr_documents(self, workflow_run: WorkflowRun) -> int: ...

    async def extract_evidence(self, workflow_run: WorkflowRun) -> int | None: ...
