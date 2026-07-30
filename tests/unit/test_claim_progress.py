from datetime import UTC, datetime
from uuid import uuid4

from claims_backend.api.claim_progress import project_claim_progress
from claims_backend.domain.claims import ClaimLifecycle
from claims_backend.domain.workflow import WorkflowEvent


def _event(
    sequence: int,
    node_name: str,
    event_type: str,
    outcome: str,
    *,
    attempt_number: int = 1,
) -> WorkflowEvent:
    return WorkflowEvent(
        id=uuid4(),
        workflow_run_id=uuid4(),
        sequence=sequence,
        node_name=node_name,
        event_type=event_type,
        attempt_number=attempt_number,
        duration_ms=25,
        outcome=outcome,
        trace_id="a" * 32,
        span_id="b" * 16,
        error_type=None,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_queued_claim_exposes_a_pollable_pending_stage_rail() -> None:
    progress = project_claim_progress(ClaimLifecycle.QUEUED, ())

    assert progress.current_stage == "ingest_claim"
    assert progress.percent == 0
    assert progress.is_terminal is False
    assert [event.status for event in progress.events] == ["PENDING"] * 7


def test_latest_retry_event_is_authoritative_for_the_stage() -> None:
    progress = project_claim_progress(
        ClaimLifecycle.QUEUED,
        (
            _event(1, "load_claim", "ENTRY", "RUNNING"),
            _event(2, "load_claim", "EXIT", "OK"),
            _event(3, "triage_documents", "ENTRY", "RUNNING"),
            _event(4, "triage_documents", "ERROR", "ERROR"),
            _event(5, "triage_documents", "ENTRY", "RUNNING", attempt_number=2),
        ),
    )

    assert progress.current_stage == "classify_documents"
    stage = next(event for event in progress.events if event.stage == "classify_documents")
    assert stage.status == "RUNNING"
    assert stage.attempt_number == 2


def test_terminal_decision_projects_finalization_after_completed_nodes() -> None:
    progress = project_claim_progress(
        ClaimLifecycle.DECIDED,
        (
            _event(1, "load_claim", "EXIT", "OK"),
            _event(2, "adjudicate", "EXIT", "OK"),
            _event(3, "commit_decision", "EXIT", "OK"),
        ),
    )

    assert progress.current_stage == "finalize_claim"
    assert progress.label == "Finalizing outcome"
    assert progress.percent == 100
    assert progress.is_terminal is True
    assert progress.events[-1].status == "COMPLETED"


def test_terminal_fallbacks_do_not_report_all_stages_as_pending() -> None:
    decided = project_claim_progress(ClaimLifecycle.DECIDED, ())
    failed = project_claim_progress(ClaimLifecycle.PROCESSING_FAILED, ())

    assert decided.current_stage == "finalize_claim"
    assert decided.events[-1].status == "COMPLETED"
    assert failed.current_stage == "ingest_claim"
    assert failed.events[0].status == "FAILED"
