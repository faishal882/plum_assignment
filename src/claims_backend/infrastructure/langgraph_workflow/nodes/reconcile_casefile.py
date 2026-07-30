from claims_backend.infrastructure.langgraph_workflow.errors import WorkflowIncompleteError
from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def reconcile_casefile_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("reconcile_casefile")
    result = await workflow._required_processor().reconcile_casefile(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    if result.reference is not None:
        reconciled = await workflow._repository.record_effect(
            _workflow_run_id(state),
            f"evidence-reconciled:v{state['claim_version']}",
            "EVIDENCE_RECONCILED",
            {
                "evidence_candidate_count": state["evidence_candidate_count"],
                "sufficient": True,
            },
        )
        frozen = await workflow._repository.record_effect(
            _workflow_run_id(state),
            f"casefile-frozen:v{state['claim_version']}",
            "CASEFILE_FROZEN",
            {
                "casefile_id": str(result.reference.id),
                "content_hash": result.reference.content_hash,
            },
        )
        await workflow._after_effect("reconcile_casefile")
        return {
            "casefile_id": str(result.reference.id),
            "casefile_hash": result.reference.content_hash,
            "effect_count": state["effect_count"] + int(reconciled) + int(frozen),
        }
    action = result.action
    if action is None:
        raise WorkflowIncompleteError("Reconciliation produced no terminal result.")
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"evidence-reconciliation-required:v{state['claim_version']}",
        "EVIDENCE_RECONCILIATION_REQUIRED",
        {
            "evidence_candidate_count": state["evidence_candidate_count"],
            "sufficient": False,
            "action_code": action.code,
        },
    )
    await workflow._after_effect("reconcile_casefile")
    return {
        "action_required": True,
        "action_code": action.code or "",
        "action_message": action.message or "",
        "observed_roles": list(action.observed_roles),
        "required_roles": list(action.required_roles),
        "affected_documents": [],
        "identity_conflict": [],
        "effect_count": state["effect_count"] + int(created),
    }
