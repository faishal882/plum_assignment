from claims_backend.domain.processing import (
    AffectedDocument,
    EarlyGateResult,
    IdentityConflictDetail,
)
from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _work_lease,
    _workflow_run,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def commit_member_action_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("commit_member_action")
    run = _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    await workflow._required_processor().commit_member_action(
        run,
        _work_lease(state),
        EarlyGateResult(
            action_required=state["action_required"],
            code=state["action_code"],
            message=state["action_message"],
            observed_roles=tuple(state["observed_roles"]),
            required_roles=tuple(state["required_roles"]),
            affected_documents=tuple(
                AffectedDocument(
                    client_document_id=document["client_document_id"],
                    observed_role=document["observed_role"],
                    requested_action=document["requested_action"],
                )
                for document in state["affected_documents"]
            ),
            identity_conflict=tuple(
                IdentityConflictDetail(
                    client_document_id=item["client_document_id"],
                    patient_name=item["patient_name"],
                )
                for item in state["identity_conflict"]
            ),
        ),
    )
    await workflow._after_effect("commit_member_action")
    return {"terminal_committed": True}
