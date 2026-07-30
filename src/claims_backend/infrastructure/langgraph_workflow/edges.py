from typing import Literal

from claims_backend.domain.processing import ProcessingRoute
from claims_backend.infrastructure.langgraph_workflow.state import WorkflowState


def _after_media_inspection(
    state: WorkflowState,
) -> Literal["freeze_casefile", "triage_documents", "render_documents", "finalize"]:
    if state["route"] == ProcessingRoute.STRUCTURED_ADJUDICATION.value:
        return "freeze_casefile"
    if state["route"] == ProcessingRoute.EARLY_TRIAGE.value:
        return "triage_documents"
    if state["route"] == ProcessingRoute.DOCUMENT_INTELLIGENCE.value:
        return "render_documents"
    return "finalize"


def _after_triage(
    state: WorkflowState,
) -> Literal["commit_member_action", "render_documents"]:
    return "commit_member_action" if state["action_required"] else "render_documents"


def _after_rendering(
    state: WorkflowState,
) -> Literal["commit_member_action", "discover_documents", "ocr_documents"]:
    if state["action_required"]:
        return "commit_member_action"
    if state["route"] == ProcessingRoute.DOCUMENT_INTELLIGENCE.value and (
        state["discovery_observation_count"] == 0
    ):
        return "discover_documents"
    return "ocr_documents"


def _after_extraction(
    state: WorkflowState,
) -> Literal["reconcile_casefile", "finalize"]:
    return "reconcile_casefile" if state["extraction_completed"] else "finalize"


def _after_reconciliation(
    state: WorkflowState,
) -> Literal["commit_member_action", "adjudicate"]:
    return "commit_member_action" if state["action_required"] else "adjudicate"
