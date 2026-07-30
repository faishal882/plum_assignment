from claims_backend.infrastructure.langgraph_workflow.helpers import _workflow_run_id
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def finalize_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("finalize")
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"skeleton-completed:v{state['claim_version']}",
        "WORKFLOW_SKELETON_COMPLETED",
        {
            "claim_id": state["claim_id"],
            "claim_version": state["claim_version"],
            "operation_key": state["operation_key"],
        },
    )
    await workflow._after_effect("finalize")
    return {
        "finalized": True,
        "effect_count": state["effect_count"] + int(created),
    }
