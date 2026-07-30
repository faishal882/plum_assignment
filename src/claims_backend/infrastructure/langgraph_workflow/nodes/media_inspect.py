from claims_backend.infrastructure.langgraph_workflow.helpers import _workflow_run
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def media_inspect_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("media_inspect")
    processor = workflow._required_processor()
    run = _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    inspection = await processor.inspect_media(run)
    route = await processor.route(run)
    created = await workflow._repository.record_effect(
        run.id,
        f"media-inspected:v{state['claim_version']}",
        "LOCAL_MEDIA_INSPECTED",
        {**inspection, "route": route.value},
    )
    await workflow._after_effect("media_inspect")
    return {
        "media_inspected": True,
        "route": route.value,
        "effect_count": state["effect_count"] + int(created),
    }
