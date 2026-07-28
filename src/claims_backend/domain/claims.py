from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class ClaimCategory(StrEnum):
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"
    CONSULTATION = "CONSULTATION"
    DENTAL = "DENTAL"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"


class ClaimLifecycle(StrEnum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    IN_REVIEW = "IN_REVIEW"
    DECIDED = "DECIDED"


@dataclass(frozen=True, slots=True)
class MemberDeduction:
    code: str
    label: str
    amount_paise: int


@dataclass(frozen=True, slots=True)
class MemberLineItemExplanation:
    concept: str
    label: str
    claimed_paise: int
    approved_paise: int
    status: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class MemberExplanation:
    summary: str
    deductions: tuple[MemberDeduction, ...]
    line_items: tuple[MemberLineItemExplanation, ...] = ()


@dataclass(frozen=True, slots=True)
class MemberAdjudication:
    recommendation: str
    approved_paise: int
    currency: str


@dataclass(frozen=True, slots=True)
class MemberActionDocument:
    client_document_id: str
    observed_role: str
    requested_action: str


@dataclass(frozen=True, slots=True)
class MemberIdentityConflict:
    client_document_id: str
    patient_name: str


@dataclass(frozen=True, slots=True)
class MemberAction:
    code: str
    message: str
    observed_document_roles: tuple[str, ...]
    required_document_roles: tuple[str, ...]
    affected_documents: tuple[MemberActionDocument, ...] = ()
    identity_conflict: tuple[MemberIdentityConflict, ...] = ()


@dataclass(frozen=True, slots=True)
class DegradedComponent:
    component: str
    criticality: str
    attempts: int
    failure_code: str
    retryable: bool
    effect_on_handling: str


@dataclass(frozen=True, slots=True)
class ProcessingQuality:
    completeness: float
    confidence: float
    degraded_components: tuple[DegradedComponent, ...]


@dataclass(frozen=True, slots=True)
class DocumentManifestItem:
    upload_index: int
    client_document_id: str


@dataclass(frozen=True, slots=True)
class SubmitClaim:
    member_id: str
    policy_id: str
    category: ClaimCategory
    treatment_date: date
    claimed_paise: int
    currency: str
    documents: tuple[DocumentManifestItem, ...]


@dataclass(frozen=True, slots=True)
class Claim:
    id: UUID
    owner_user_id: UUID
    owner_username_snapshot: str
    version: int
    member_id: str
    policy_id: str
    category: ClaimCategory
    treatment_date: date
    claimed_paise: int
    currency: str
    lifecycle: ClaimLifecycle
    adjudication: MemberAdjudication | None
    explanation: MemberExplanation | None
    action: MemberAction | None
    handling_status: str | None
    processing_quality: ProcessingQuality | None
    review_task_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReplaceDocument:
    expected_version: int
    client_document_id: str


@dataclass(frozen=True, slots=True)
class DocumentReplacementResult:
    action_id: UUID
    claim: Claim
    previous_version: int
    result_version: int
    result_lifecycle: ClaimLifecycle
    client_document_id: str
    document_version: int
    replayed: bool
