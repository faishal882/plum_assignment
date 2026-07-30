from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def freeze_casefile_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("freeze_casefile")
    processor = workflow._required_processor()
    reference = await processor.freeze_casefile(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"casefile-frozen:v{state['claim_version']}",
        "CASEFILE_FROZEN",
        {
            "casefile_id": str(reference.id),
            "content_hash": reference.content_hash,
        },
    )
    await workflow._after_effect("freeze_casefile")
    return {
        "casefile_id": str(reference.id),
        "casefile_hash": reference.content_hash,
        "effect_count": state["effect_count"] + int(created),
    }
