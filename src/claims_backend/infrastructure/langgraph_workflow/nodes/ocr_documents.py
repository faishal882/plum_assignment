from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def ocr_documents_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("ocr_documents")
    observation_count = await workflow._required_processor().ocr_documents(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"page-ocr-completed:v{state['claim_version']}",
        "PAGE_OCR_COMPLETED",
        {
            "rendered_page_count": state["rendered_page_count"],
            "observation_count": observation_count,
        },
    )
    await workflow._after_effect("ocr_documents")
    return {
        "ocr_observation_count": observation_count,
        "effect_count": state["effect_count"] + int(created),
    }
