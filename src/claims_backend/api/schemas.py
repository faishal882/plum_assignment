from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from claims_backend.domain.claims import ClaimCategory
from claims_backend.domain.reviews import ReviewAction


class DocumentManifestItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_index: int = Field(ge=0)
    client_document_id: str = Field(min_length=1, max_length=128)


class ClaimMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=64)
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Literal["INR"]
    documents: list[DocumentManifestItemRequest] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_document_manifest(self) -> "ClaimMetadataRequest":
        indexes = [document.upload_index for document in self.documents]
        if len(indexes) != len(set(indexes)):
            raise ValueError("document upload indexes must be unique")
        if sorted(indexes) != list(range(len(indexes))):
            raise ValueError("document upload indexes must be contiguous and start at zero")

        document_ids = [document.client_document_id.casefold() for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("client document identifiers must be unique")
        return self


class ProgressResponse(BaseModel):
    current_stage: str
    is_terminal: bool


class ClaimReceiptResponse(BaseModel):
    claim_id: UUID
    version: int
    lifecycle_status: str
    status_url: str


class ClaimResponse(BaseModel):
    claim_id: UUID
    version: int
    member_id: str
    policy_id: str
    claim_category: str
    treatment_date: date
    claimed_amount: Decimal
    currency: str
    lifecycle_status: str
    progress: ProgressResponse
    adjudication: "MemberAdjudicationResponse | None" = None
    explanation: "MemberExplanationResponse | None" = None
    action: "MemberActionResponse | None" = None
    handling_status: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("claimed_amount")
    def serialize_claimed_amount(self, amount: Decimal) -> str:
        return f"{amount:.2f}"


class MemberAdjudicationResponse(BaseModel):
    recommendation: str
    approved_amount: Decimal
    currency: str

    @field_serializer("approved_amount")
    def serialize_approved_amount(self, amount: Decimal) -> str:
        return f"{amount:.2f}"


class MemberDeductionResponse(BaseModel):
    code: str
    label: str
    amount: Decimal

    @field_serializer("amount")
    def serialize_amount(self, amount: Decimal) -> str:
        return f"{amount:.2f}"


class MemberExplanationResponse(BaseModel):
    summary: str
    deductions: list[MemberDeductionResponse]
    line_items: list["MemberLineItemExplanationResponse"] | None = None


class MemberLineItemExplanationResponse(BaseModel):
    concept: str
    label: str
    claimed_amount: Decimal
    approved_amount: Decimal
    status: str
    reason_code: str

    @field_serializer("claimed_amount", "approved_amount")
    def serialize_amount(self, amount: Decimal) -> str:
        return f"{amount:.2f}"


class MemberActionResponse(BaseModel):
    code: str
    message: str
    observed_document_roles: list[str]
    required_document_roles: list[str]
    affected_documents: list["AffectedDocumentResponse"] | None = None
    identity_conflict: list["IdentityConflictResponse"] | None = None


class AffectedDocumentResponse(BaseModel):
    client_document_id: str
    observed_role: str
    requested_action: str


class IdentityConflictResponse(BaseModel):
    client_document_id: str
    patient_name: str


class ReplaceDocumentCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["REPLACE_DOCUMENT"]
    expected_version: int = Field(ge=1)
    client_document_id: str = Field(min_length=1, max_length=128)


class ReplacementDocumentResponse(BaseModel):
    client_document_id: str
    version: int


class ClaimActionResponse(BaseModel):
    action_id: UUID
    action_type: Literal["REPLACE_DOCUMENT"]
    claim_id: UUID
    previous_version: int
    version: int
    lifecycle_status: str
    document: ReplacementDocumentResponse
    status_url: str


class ErrorDetailResponse(BaseModel):
    location: list[str | int] | None = None
    message: str
    type: str | None = None


class ErrorBodyResponse(BaseModel):
    code: str
    message: str
    details: list[ErrorDetailResponse] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBodyResponse


class ReviewTaskSummaryResponse(BaseModel):
    id: UUID
    claim_id: UUID
    claim_version: int
    status: str
    signal_codes: list[str]
    machine_recommendation: str
    machine_approved_amount: Decimal
    currency: str
    allowed_actions: list[str]
    created_at: datetime
    resolved_at: datetime | None

    @field_serializer("machine_approved_amount")
    def serialize_machine_amount(self, amount: Decimal) -> str:
        return f"{amount:.2f}"


class ReviewTaskDetailResponse(BaseModel):
    task: ReviewTaskSummaryResponse
    evidence: dict[str, object]
    conflicts: list[dict[str, object]]
    rules: list[dict[str, object]]
    calculations: list[dict[str, object]]
    failures: list[dict[str, object]]


class ReviewCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    expected_claim_version: int = Field(ge=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    reason_note: str = Field(min_length=10, max_length=1000)
    amended_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def amend_requires_amount(self) -> "ReviewCommandRequest":
        if self.action is ReviewAction.AMEND and self.amended_amount is None:
            raise ValueError("AMEND requires amended_amount")
        if self.action is not ReviewAction.AMEND and self.amended_amount is not None:
            raise ValueError("amended_amount is valid only for AMEND")
        return self


class ReviewResolutionResponse(BaseModel):
    id: UUID
    task_id: UUID
    action: str
    reason_code: str
    reason_note: str
    before: dict[str, object]
    after: dict[str, object]
    actor_user_id: UUID
    actor_username: str
    created_at: datetime
    replayed: bool
