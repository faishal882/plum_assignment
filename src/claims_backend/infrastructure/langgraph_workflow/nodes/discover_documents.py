from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def discover_documents_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("discover_documents")
    observation_count = await workflow._required_processor().discover_documents(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"discovery-ocr-completed:v{state['claim_version']}",
        "DISCOVERY_OCR_COMPLETED",
        {
            "rendered_page_count": state["rendered_page_count"],
            "observation_count": observation_count,
        },
    )
    await workflow._after_effect("discover_documents")
    return {
        "discovery_observation_count": observation_count,
        "effect_count": state["effect_count"] + int(created),
    }
