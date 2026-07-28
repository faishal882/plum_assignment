from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ReviewTaskStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ReviewAction(StrEnum):
    ACCEPT = "ACCEPT"
    AMEND = "AMEND"
    REJECT = "REJECT"
    REQUEST_DOCUMENT = "REQUEST_DOCUMENT"


@dataclass(frozen=True, slots=True)
class ReviewCommand:
    action: ReviewAction
    expected_claim_version: int
    reason_code: str
    reason_note: str
    amended_paise: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewTaskSummary:
    id: UUID
    claim_id: UUID
    claim_version: int
    status: ReviewTaskStatus
    signal_codes: tuple[str, ...]
    machine_recommendation: str
    machine_approved_paise: int
    currency: str
    allowed_actions: tuple[ReviewAction, ...]
    created_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReviewTaskDetail:
    summary: ReviewTaskSummary
    evidence: dict[str, object]
    conflicts: tuple[dict[str, object], ...]
    rules: tuple[dict[str, object], ...]
    calculations: tuple[dict[str, object], ...]
    failures: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ReviewResolution:
    id: UUID
    task_id: UUID
    action: ReviewAction
    reason_code: str
    reason_note: str
    before: dict[str, object]
    after: dict[str, object]
    actor_user_id: UUID
    actor_username: str
    created_at: datetime
    replayed: bool = False
