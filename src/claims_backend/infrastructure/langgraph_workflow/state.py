from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from claims_backend.domain.work import WorkLease


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Ephemeral execution authority; never persisted in a LangGraph checkpoint."""

    lease: WorkLease
    workflow_run_id: UUID
    claim_id: UUID
    claim_version: int


_ACTIVE_RUNTIME_CONTEXT: ContextVar[WorkflowRuntimeContext] = ContextVar(
    "claims_workflow_runtime_context"
)

_NODE_COMPONENTS = {
    "load_claim": "persistence",
    "finalize": "persistence",
    "media_inspect": "document_intelligence",
    "freeze_casefile": "reconciliation",
    "adjudicate": "policy",
    "commit_decision": "persistence",
    "triage_documents": "identity",
    "render_documents": "document_intelligence",
    "discover_documents": "textract",
    "ocr_documents": "textract",
    "extract_evidence": "bedrock",
    "reconcile_casefile": "reconciliation",
    "commit_member_action": "persistence",
}

_TERMINAL_COMMIT_NODES = frozenset({"commit_decision", "commit_member_action"})


class WorkflowState(TypedDict):
    workflow_run_id: str
    claim_id: str
    claim_version: int
    work_item_id: str
    operation_key: str
    claim_loaded: bool
    finalized: bool
    route: str
    media_inspected: bool
    casefile_id: str
    casefile_hash: str
    proposal_hash: str
    action_required: bool
    action_code: str
    action_message: str
    observed_roles: list[str]
    required_roles: list[str]
    affected_documents: list[dict[str, str]]
    identity_conflict: list[dict[str, str]]
    rendered_page_count: int
    discovery_observation_count: int
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    effect_count: int


class WorkflowUpdate(TypedDict, total=False):
    claim_loaded: bool
    finalized: bool
    route: str
    media_inspected: bool
    casefile_id: str
    casefile_hash: str
    proposal_hash: str
    action_required: bool
    action_code: str
    action_message: str
    observed_roles: list[str]
    required_roles: list[str]
    affected_documents: list[dict[str, str]]
    identity_conflict: list[dict[str, str]]
    rendered_page_count: int
    discovery_observation_count: int
    ocr_observation_count: int
    evidence_candidate_count: int
    extraction_completed: bool
    terminal_committed: bool
    effect_count: int


def _active_lease() -> WorkLease:
    return _ACTIVE_RUNTIME_CONTEXT.get().lease
