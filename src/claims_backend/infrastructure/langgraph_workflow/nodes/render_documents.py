from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def render_documents_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("render_documents")
    result = await workflow._required_processor().render_documents(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    action = result.action
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"document-pages-prepared:v{state['claim_version']}",
        ("DOCUMENT_RENDERING_BLOCKED" if action is not None else "DOCUMENT_PAGES_RENDERED"),
        {
            "rendered_page_count": result.rendered_page_count,
            "action_required": action is not None,
            "action_code": None if action is None else action.code,
        },
    )
    await workflow._after_effect("render_documents")
    if action is None:
        return {
            "rendered_page_count": result.rendered_page_count,
            "effect_count": state["effect_count"] + int(created),
        }
    return {
        "rendered_page_count": result.rendered_page_count,
        "action_required": True,
        "action_code": action.code or "",
        "action_message": action.message or "",
        "observed_roles": list(action.observed_roles),
        "required_roles": list(action.required_roles),
        "affected_documents": [
            {
                "client_document_id": document.client_document_id,
                "observed_role": document.observed_role,
                "requested_action": document.requested_action,
            }
            for document in action.affected_documents
        ],
        "identity_conflict": [],
        "effect_count": state["effect_count"] + int(created),
    }
