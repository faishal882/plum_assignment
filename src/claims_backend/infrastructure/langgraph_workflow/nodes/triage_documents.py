from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _workflow_run,
    _workflow_run_id,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def triage_documents_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("triage_documents")
    result = await workflow._required_processor().triage_documents(
        _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    )
    created = await workflow._repository.record_effect(
        _workflow_run_id(state),
        f"document-triage-completed:v{state['claim_version']}",
        "DOCUMENT_TRIAGE_COMPLETED",
        {
            "action_required": result.action_required,
            "observed_document_roles": list(result.observed_roles),
            "required_document_roles": list(result.required_roles),
        },
    )
    await workflow._after_effect("triage_documents")
    return {
        "action_required": result.action_required,
        "action_code": result.code or "",
        "action_message": result.message or "",
        "observed_roles": list(result.observed_roles),
        "required_roles": list(result.required_roles),
        "affected_documents": [
            {
                "client_document_id": document.client_document_id,
                "observed_role": document.observed_role,
                "requested_action": document.requested_action,
            }
            for document in result.affected_documents
        ],
        "identity_conflict": [
            {
                "client_document_id": item.client_document_id,
                "patient_name": item.patient_name,
            }
            for item in result.identity_conflict
        ],
        "effect_count": state["effect_count"] + int(created),
    }
