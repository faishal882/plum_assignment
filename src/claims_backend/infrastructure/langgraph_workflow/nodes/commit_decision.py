from uuid import UUID

from claims_backend.infrastructure.langgraph_workflow.helpers import (
    _work_lease,
    _workflow_run,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    WorkflowState,
    WorkflowUpdate,
)


async def commit_decision_node(state: WorkflowState, workflow: "LangGraphClaimWorkflow") -> WorkflowUpdate:  # type: ignore[name-defined] # noqa: F821
    await workflow._before_node("commit_decision")
    run = _workflow_run(state, workflow.graph_name, workflow.graph_version, workflow.execution_contract)
    await workflow._required_processor().commit_decision(
        run,
        _work_lease(state),
        UUID(state["casefile_id"]),
    )
    await workflow._after_effect("commit_decision")
    return {"terminal_committed": True}
