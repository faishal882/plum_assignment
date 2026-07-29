from datetime import UTC, datetime
from uuid import uuid4

import pytest

from claims_backend.application.work import WorkCompleted
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import ExecutionContract, WorkflowRun, WorkflowRunStatus


@pytest.mark.asyncio
async def test_existing_workflow_uses_its_pinned_runtime_contract() -> None:
    lease = WorkLease(
        work_item_id=uuid4(),
        claim_id=uuid4(),
        claim_version=1,
        operation_key="PROCESS",
        worker_id="worker",
        lease_token=uuid4(),
        leased_at=datetime.now(UTC),
        lease_until=datetime.now(UTC),
        available_at=datetime.now(UTC),
        attempt_number=1,
        max_attempts=3,
    )
    historical = _contract("complex-extraction-prompt-v3")
    repository = _Repository(_run(lease, historical))
    current_runtime = _Runtime(_contract("complex-extraction-prompt-v4"))
    historical_runtime = _Runtime(historical)

    async def resolve(existing: WorkflowRun | None) -> _Runtime:
        assert existing is not None
        assert existing.execution_contract == historical
        return historical_runtime

    result = await ClaimWorkflowProcessor(
        repository,
        current_runtime,
        runtime_resolver=resolve,
    ).process(lease)

    assert result == WorkCompleted()
    assert repository.requested_contract == historical
    assert historical_runtime.runs == 1
    assert current_runtime.runs == 0


class _Repository:
    def __init__(self, run: WorkflowRun) -> None:
        self.run = run
        self.requested_contract: ExecutionContract | None = None

    async def get_by_work_item(self, work_item_id):
        assert work_item_id == self.run.work_item_id
        return self.run

    async def get_or_create(self, lease, graph_name, graph_version, execution_contract):
        assert lease.work_item_id == self.run.work_item_id
        assert graph_name == self.run.graph_name
        assert graph_version == self.run.graph_version
        self.requested_contract = execution_contract
        return self.run

    async def mark_running(self, workflow_run_id):
        assert workflow_run_id == self.run.id
        return self.run

    async def mark_completed(self, workflow_run_id):
        assert workflow_run_id == self.run.id
        return self.run


class _Runtime:
    graph_name = "claim-processing"
    graph_version = "claim-processing-v7"

    def __init__(self, contract: ExecutionContract) -> None:
        self.execution_contract = contract
        self.runs = 0

    async def setup(self) -> None:
        return None

    async def run(self, workflow_run, lease, *, resume):
        assert workflow_run.execution_contract == self.execution_contract
        assert lease.work_item_id == workflow_run.work_item_id
        assert resume is False
        self.runs += 1
        return False


def _contract(prompt_version: str) -> ExecutionContract:
    return ExecutionContract(
        schema_version="execution-contract-v1",
        execution_profile="RECORDED_LOCAL",
        ocr_provider_name="RECORDED_DISCOVERY_OCR",
        ocr_provider_version="recorded-discovery-v1",
        model_provider_name="RECORDED_DOCUMENT_MODEL",
        model_provider_version="recorded-document-v1",
        model_routes=(
            ("FAST_TRIAGE", "model", "region", "fast-triage-prompt-v2", "triage-output-v3"),
            ("COMPLEX_EXTRACTION", "model", "region", prompt_version, "complex-extraction-v1"),
        ),
    )


def _run(lease: WorkLease, contract: ExecutionContract) -> WorkflowRun:
    now = datetime.now(UTC)
    return WorkflowRun(
        id=uuid4(),
        work_item_id=lease.work_item_id,
        claim_id=lease.claim_id,
        claim_version=lease.claim_version,
        operation_key=lease.operation_key,
        graph_name="claim-processing",
        graph_version="claim-processing-v7",
        execution_contract=contract,
        status=WorkflowRunStatus.PENDING,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
