import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy.engine import make_url

from claims_backend.application.work import LeaseLostError
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import (
    ExecutionContract,
    WorkflowRun,
    WorkflowRunStatus,
)
from claims_backend.infrastructure.langgraph_workflow.state import (
    _TERMINAL_COMMIT_NODES,
    WorkflowState,
    _active_lease,
)


def _workflow_run_id(state: WorkflowState) -> UUID:
    return UUID(state["workflow_run_id"])


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _workflow_run(
    state: WorkflowState,
    graph_name: str,
    graph_version: str,
    execution_contract: ExecutionContract,
) -> WorkflowRun:
    return WorkflowRun(
        id=_workflow_run_id(state),
        work_item_id=UUID(state["work_item_id"]),
        claim_id=UUID(state["claim_id"]),
        claim_version=state["claim_version"],
        operation_key=state["operation_key"],
        graph_name=graph_name,
        graph_version=graph_version,
        execution_contract=execution_contract,
        status=WorkflowRunStatus.RUNNING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        completed_at=None,
    )


def _work_lease(_: WorkflowState) -> WorkLease:
    return _active_lease()


def _lease_id_sha256(lease: WorkLease) -> str:
    return sha256(str(lease.lease_token).encode("ascii")).hexdigest()


def _terminal_outcome_attributes(
    *,
    node_name: str | None,
    error: Exception | None = None,
    committed: bool = False,
) -> dict[str, str]:
    if isinstance(error, LeaseLostError):
        return {
            "lease.validation.outcome": "REJECTED_STALE",
            "terminal.commit.outcome": "NOT_COMMITTED",
        }
    if node_name in _TERMINAL_COMMIT_NODES:
        return {
            "lease.validation.outcome": "ACCEPTED" if committed else "NOT_EVALUATED",
            "terminal.commit.outcome": "COMMITTED" if committed else "NOT_COMMITTED",
        }
    return {
        "lease.validation.outcome": "NOT_EVALUATED",
        "terminal.commit.outcome": "NOT_COMMITTED",
    }


def _checkpoint_url(database_url: str) -> str:
    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("LangGraph checkpoints require PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)
