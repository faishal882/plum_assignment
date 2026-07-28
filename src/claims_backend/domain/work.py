from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class RetryDisposition(StrEnum):
    SCHEDULED = "SCHEDULED"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True, slots=True)
class WorkLease:
    work_item_id: UUID
    claim_id: UUID
    operation_key: str
    worker_id: str
    lease_token: UUID
    leased_at: datetime
    lease_until: datetime
    available_at: datetime
    attempt_number: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class WorkRequest:
    claim_id: UUID
    operation_key: str
    available_at: datetime
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class WorkRef:
    work_item_id: UUID
    claim_id: UUID
    operation_key: str
    created: bool
