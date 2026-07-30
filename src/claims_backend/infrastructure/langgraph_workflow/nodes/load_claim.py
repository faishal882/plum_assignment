from claims_backend.infrastructure.langgraph_workflow.helpers import _workflow_run_id
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def load_claim_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("load_claim")
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"claim-loaded:v{state['claim_version']}",
        "CLAIM_VERSION_LOADED",
        {
            "claim_id": state["claim_id"],
            "claim_version": state["claim_version"],
            "work_item_id": state["work_item_id"],
        },
    )
    await workflow._after_effect("load_claim")
    return {
        "claim_loaded": True,
        "effect_count": state["effect_count"] + int(created),
    }
