from uuid import UUID

from claims_backend.infrastructure.langgraph_workflow.helpers import _workflow_run_id
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def adjudicate_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("adjudicate")
    proposal_hash = await workflow._required_processor().evaluate_casefile(
        UUID(state["casefile_id"])
    )
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"adjudication-proposed:v{state['claim_version']}",
        "ADJUDICATION_PROPOSED",
        {
            "casefile_id": state["casefile_id"],
            "proposal_hash": proposal_hash,
        },
    )
    await workflow._after_effect("adjudicate")
    return {
        "proposal_hash": proposal_hash,
        "effect_count": state["effect_count"] + int(created),
    }
