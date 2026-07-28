from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from claims_backend.domain.claims import ClaimCategory


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
