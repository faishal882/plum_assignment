from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from claims_backend.domain.adjudication import RuleResult


class ProcessingRoute(StrEnum):
    NONE = "NONE"
    STRUCTURED_ADJUDICATION = "STRUCTURED_ADJUDICATION"
    EARLY_TRIAGE = "EARLY_TRIAGE"


@dataclass(frozen=True, slots=True)
class FrozenCasefileRef:
    id: UUID
    content_hash: str


@dataclass(frozen=True, slots=True)
class CasefileTrace:
    id: UUID
    content_hash: str


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    id: UUID
    recommendation: str
    approved_paise: int
    canonical_hash: str


@dataclass(frozen=True, slots=True)
class ClaimProcessingTrace:
    casefile: CasefileTrace
    decision: DecisionTrace
    rule_results: tuple[RuleResult, ...]
    work_status: str
    workflow_status: str
