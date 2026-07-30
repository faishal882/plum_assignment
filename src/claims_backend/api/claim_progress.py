"""Frontend-safe projection of durable workflow events.

The workflow graph is allowed to change internally.  This module is the stable
contract between its node-level audit trail and the member-facing progress rail.
It intentionally exposes no trace payloads, OCR text, or model inputs.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from claims_backend.api.schemas import ProgressEventResponse, ProgressResponse
from claims_backend.domain.claims import ClaimLifecycle
from claims_backend.domain.workflow import WorkflowEvent

ProgressStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]


@dataclass(frozen=True, slots=True)
class _StageDefinition:
    stage: str
    label: str
    percent: int
    node_names: tuple[str, ...]
    pending_summary: str
    running_summary: str
    completed_summary: str


_STAGES: tuple[_StageDefinition, ...] = (
    _StageDefinition(
        stage="ingest_claim",
        label="Ingesting claim",
        percent=10,
        node_names=("load_claim", "media_inspect"),
        pending_summary="Waiting for a worker to start processing.",
        running_summary="Securing uploaded documents and creating the claim packet.",
        completed_summary="Claim packet and uploaded documents verified.",
    ),
    _StageDefinition(
        stage="classify_documents",
        label="Identifying documents",
        percent=25,
        node_names=("discover_documents", "triage_documents"),
        pending_summary="Waiting to identify document types.",
        running_summary="Identifying document type, patient name, and readability.",
        completed_summary="Document type and readability checks completed.",
    ),
    _StageDefinition(
        stage="render_documents",
        label="Rendering documents",
        percent=40,
        node_names=("render_documents",),
        pending_summary="Waiting to render document pages.",
        running_summary="Rendering document pages for OCR and audit provenance.",
        completed_summary="Document pages rendered for downstream processing.",
    ),
    _StageDefinition(
        stage="read_documents",
        label="Reading document text",
        percent=55,
        node_names=("ocr_documents",),
        pending_summary="Waiting to read document text.",
        running_summary="Reading document text with OCR.",
        completed_summary="OCR observations captured from the documents.",
    ),
    _StageDefinition(
        stage="extract_evidence",
        label="Extracting evidence",
        percent=70,
        node_names=("extract_evidence", "reconcile_casefile", "freeze_casefile"),
        pending_summary="Waiting to extract claim evidence.",
        running_summary="Extracting and reconciling evidence for the claim.",
        completed_summary="Required claim evidence reconciled.",
    ),
    _StageDefinition(
        stage="check_policy",
        label="Checking policy",
        percent=85,
        node_names=("adjudicate",),
        pending_summary="Waiting to apply policy rules.",
        running_summary="Checking coverage and policy rules.",
        completed_summary="Policy rules evaluated.",
    ),
    _StageDefinition(
        stage="finalize_claim",
        label="Finalizing outcome",
        percent=100,
        node_names=("commit_decision", "commit_member_action", "finalize"),
        pending_summary="Waiting to finalize the claim outcome.",
        running_summary="Recording the claim outcome.",
        completed_summary="Claim outcome recorded.",
    ),
)

_TERMINAL_LIFECYCLES = {
    ClaimLifecycle.ACTION_REQUIRED,
    ClaimLifecycle.DECIDED,
    ClaimLifecycle.PROCESSING_FAILED,
}


def project_claim_progress(
    lifecycle: ClaimLifecycle,
    events: Iterable[WorkflowEvent],
) -> ProgressResponse:
    """Build the progress rail from append-only workflow events.

    The newest event within a stage is authoritative.  This naturally handles
    retries: a later ENTRY replaces an earlier ERROR as the stage's current
    state while preserving the complete audit trail in PostgreSQL/Phoenix.
    """
    ordered_events = sorted(events, key=lambda event: event.sequence)
    stage_events: list[ProgressEventResponse] = []
    current_index = 0
    current_sequence = -1

    for index, definition in enumerate(_STAGES):
        latest = _latest_for_stage(ordered_events, definition)
        status = _status(latest)
        event = ProgressEventResponse(
            stage=definition.stage,
            label=definition.label,
            status=status,
            summary=_summary(definition, status),
            attempt_number=None if latest is None else latest.attempt_number,
            duration_ms=(
                None if latest is None or latest.event_type == "ENTRY" else latest.duration_ms
            ),
            completed_at=(
                None
                if latest is None or status not in {"COMPLETED", "FAILED"}
                else latest.created_at
            ),
        )
        stage_events.append(event)
        if latest is not None and latest.sequence >= current_sequence:
            current_index = index
            current_sequence = latest.sequence

    if lifecycle is ClaimLifecycle.PROCESSING_FAILED:
        current_index = 0 if current_sequence < 0 else current_index
        current = stage_events[current_index]
        if current.status != "FAILED":
            stage_events[current_index] = current.model_copy(
                update={
                    "status": "FAILED",
                    "summary": f"{current.label} could not be completed.",
                    "completed_at": None,
                }
            )
    elif lifecycle in {ClaimLifecycle.DECIDED, ClaimLifecycle.ACTION_REQUIRED}:
        current_index = len(_STAGES) - 1
        final_stage = stage_events[current_index]
        if final_stage.status == "PENDING":
            stage_events[current_index] = final_stage.model_copy(
                update={
                    "status": "COMPLETED",
                    "summary": _STAGES[current_index].completed_summary,
                }
            )

    current = stage_events[current_index]
    percent = 0 if current_sequence < 0 else _STAGES[current_index].percent
    return ProgressResponse(
        current_stage=current.stage,
        label=current.label,
        percent=percent,
        is_terminal=lifecycle in _TERMINAL_LIFECYCLES,
        events=stage_events,
    )


def _latest_for_stage(
    events: Iterable[WorkflowEvent],
    definition: _StageDefinition,
) -> WorkflowEvent | None:
    return next(
        (event for event in reversed(tuple(events)) if event.node_name in definition.node_names),
        None,
    )


def _status(event: WorkflowEvent | None) -> ProgressStatus:
    if event is None:
        return "PENDING"
    if event.event_type == "ENTRY" and event.outcome == "RUNNING":
        return "RUNNING"
    if event.event_type == "ERROR" or event.outcome == "ERROR":
        return "FAILED"
    return "COMPLETED"


def _summary(definition: _StageDefinition, status: ProgressStatus) -> str:
    if status == "PENDING":
        return definition.pending_summary
    if status == "RUNNING":
        return definition.running_summary
    if status == "FAILED":
        return f"{definition.label} could not be completed."
    return definition.completed_summary
