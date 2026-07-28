from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkflowRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: UUID
    work_item_id: UUID
    claim_id: UUID
    claim_version: int
    operation_key: str
    graph_name: str
    graph_version: str
    status: WorkflowRunStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkflowEffect:
    id: UUID
    workflow_run_id: UUID
    effect_key: str
    effect_type: str
    payload: dict[str, object]
    created_at: datetime
