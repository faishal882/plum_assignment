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
    version: int
    member_id: str
    policy_id: str
    category: ClaimCategory
    treatment_date: date
    claimed_paise: int
    currency: str
    lifecycle: ClaimLifecycle
    created_at: datetime
    updated_at: datetime
