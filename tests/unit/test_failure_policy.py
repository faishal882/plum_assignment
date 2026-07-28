from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from claims_backend.application.failure_policy import (
    FailureComponent,
    FailureCriticality,
    RetrySchedule,
    classify_processing_failure,
    retry_schedule_from_settings,
)
from claims_backend.application.work import WorkFailed, WorkRetry
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.extraction import ModelProviderError, ModelSemanticValidationError
from claims_backend.domain.ocr import OcrMalformedResponseError, OcrTimeoutError
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import WorkflowRun, WorkflowRunStatus
from claims_backend.policy.adjudicator import UnsafeCasefileError

_NOW = datetime(2026, 7, 29, 10, tzinfo=UTC)
_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_failure_classification_separates_retryability_and_criticality() -> None:
    timeout = classify_processing_failure(OcrTimeoutError("timeout"))
    malformed = classify_processing_failure(OcrMalformedResponseError("malformed"))
    semantic = classify_processing_failure(ModelSemanticValidationError("invalid fact"))
    provider = classify_processing_failure(
        ModelProviderError("unavailable", code="BEDROCK_UNAVAILABLE", retryable=True)
    )
    policy = classify_processing_failure(UnsafeCasefileError("contradiction"))

    assert timeout is not None
    assert timeout.component is FailureComponent.OCR
    assert timeout.criticality is FailureCriticality.CRITICAL
    assert timeout.retryable is True
    assert timeout.code == "TEXTRACT_TIMEOUT"

    assert malformed is not None
    assert malformed.retryable is False
    assert semantic is not None
    assert semantic.component is FailureComponent.EVIDENCE_EXTRACTION
    assert semantic.retryable is False
    assert provider is not None
    assert provider.code == "BEDROCK_UNAVAILABLE"
    assert provider.retryable is True
    assert policy is not None
    assert policy.component is FailureComponent.POLICY
    assert policy.retryable is False
    assert classify_processing_failure(RuntimeError("unexpected")) is None


def test_retry_schedule_is_exponential_bounded_and_jittered() -> None:
    schedule = RetrySchedule(
        base_delay=timedelta(seconds=2),
        maximum_delay=timedelta(seconds=10),
        jitter_ratio=0.25,
        clock=lambda: _NOW,
        entropy=lambda: 0.5,
    )

    assert schedule.available_at(attempt_number=1) == _NOW + timedelta(seconds=2.25)
    assert schedule.available_at(attempt_number=2) == _NOW + timedelta(seconds=4.5)
    assert schedule.available_at(attempt_number=4) == _NOW + timedelta(seconds=10)


def test_retry_schedule_uses_runtime_configuration() -> None:
    schedule = retry_schedule_from_settings(
        Settings(
            database_url="postgresql+psycopg://local/test",
            retry_base_seconds=3,
            retry_max_seconds=20,
            retry_jitter_ratio=0.5,
        ),
        clock=lambda: _NOW,
        entropy=lambda: 1,
    )

    assert schedule.available_at(attempt_number=1) == _NOW + timedelta(seconds=4.5)


@pytest.mark.asyncio
async def test_workflow_maps_only_known_failures_to_retry_or_terminal_failure() -> None:
    lease = _lease()
    retrying = ClaimWorkflowProcessor(
        _Repository(),
        _FailingRuntime(OcrTimeoutError("timeout")),
        retry_schedule=RetrySchedule(
            clock=lambda: _NOW,
            entropy=lambda: 0,
        ),
    )
    retry = await retrying.process(lease)

    assert retry == WorkRetry(
        failure_code="TEXTRACT_TIMEOUT",
        available_at=_NOW + timedelta(seconds=2),
    )

    deterministic = ClaimWorkflowProcessor(
        _Repository(),
        _FailingRuntime(ModelSemanticValidationError("unsupported fact")),
    )
    failed = await deterministic.process(lease)
    assert failed == WorkFailed(failure_code="MODEL_SEMANTIC_VALIDATION_FAILED")

    unknown = ClaimWorkflowProcessor(_Repository(), _FailingRuntime(RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        await unknown.process(lease)


class _Repository:
    async def get_or_create(
        self,
        lease: WorkLease,
        graph_name: str,
        graph_version: str,
    ) -> WorkflowRun:
        return _run(WorkflowRunStatus.PENDING)

    async def mark_running(self, workflow_run_id: UUID) -> WorkflowRun:
        return _run(WorkflowRunStatus.RUNNING)


class _FailingRuntime:
    graph_name = "claim-processing"
    graph_version = "v1"

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def run(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        *,
        resume: bool,
    ) -> bool:
        raise self._error


def _run(status: WorkflowRunStatus) -> WorkflowRun:
    return WorkflowRun(
        id=_ID,
        work_item_id=_ID,
        claim_id=_ID,
        claim_version=1,
        operation_key="claim:1:process:v1",
        graph_name="claim-processing",
        graph_version="v1",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def _lease() -> WorkLease:
    return WorkLease(
        work_item_id=_ID,
        claim_id=_ID,
        claim_version=1,
        operation_key="claim:1:process:v1",
        worker_id="worker",
        lease_token=_ID,
        leased_at=_NOW,
        lease_until=_NOW + timedelta(minutes=5),
        available_at=_NOW,
        attempt_number=1,
        max_attempts=3,
    )
