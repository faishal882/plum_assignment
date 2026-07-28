from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkflowRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    """The immutable, non-sensitive implementation contract for one workflow run."""

    schema_version: str
    execution_profile: str
    ocr_provider_name: str
    ocr_provider_version: str
    model_provider_name: str
    model_provider_version: str
    model_routes: tuple[tuple[str, str, str, str, str], ...]

    @classmethod
    def unspecified(cls) -> "ExecutionContract":
        return cls(
            schema_version="execution-contract-v1",
            execution_profile="UNSPECIFIED",
            ocr_provider_name="UNSPECIFIED",
            ocr_provider_version="UNSPECIFIED",
            model_provider_name="UNSPECIFIED",
            model_provider_version="UNSPECIFIED",
            model_routes=(),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_profile": self.execution_profile,
            "ocr_provider": {
                "name": self.ocr_provider_name,
                "version": self.ocr_provider_version,
            },
            "model_provider": {
                "name": self.model_provider_name,
                "version": self.model_provider_version,
            },
            "model_routes": [
                {
                    "route": route,
                    "model_id": model_id,
                    "region": region,
                    "prompt_version": prompt_version,
                    "schema_version": schema_version,
                }
                for route, model_id, region, prompt_version, schema_version in self.model_routes
            ],
        }


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    id: UUID
    work_item_id: UUID
    claim_id: UUID
    claim_version: int
    operation_key: str
    graph_name: str
    graph_version: str
    execution_contract: ExecutionContract
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


@dataclass(frozen=True, slots=True)
class NewWorkflowEvent:
    node_name: str
    event_type: str
    attempt_number: int
    duration_ms: int
    outcome: str
    trace_id: str | None
    span_id: str | None
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    id: UUID
    workflow_run_id: UUID
    sequence: int
    node_name: str
    event_type: str
    attempt_number: int
    duration_ms: int
    outcome: str
    trace_id: str | None
    span_id: str | None
    error_type: str | None
    created_at: datetime
