from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def extract_evidence_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("extract_evidence")
    candidate_count = await workflow._required_processor().extract_evidence(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    if candidate_count is None:
        return {}
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"structured-extraction-completed:v{state['claim_version']}",
        "STRUCTURED_EXTRACTION_COMPLETED",
        {
            "ocr_observation_count": state["ocr_observation_count"],
            "evidence_candidate_count": candidate_count,
        },
    )
    await workflow._after_effect("extract_evidence")
    return {
        "evidence_candidate_count": candidate_count,
        "extraction_completed": True,
        "effect_count": state["effect_count"] + int(created),
    }
