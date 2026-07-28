from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentRole(StrEnum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DENTAL_REPORT = "DENTAL_REPORT"
    PRE_AUTHORIZATION = "PRE_AUTHORIZATION"
    UNKNOWN = "UNKNOWN"


class Readability(StrEnum):
    READABLE = "READABLE"
    UNREADABLE = "UNREADABLE"
    UNKNOWN = "UNKNOWN"


class IdentityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(pattern=r"^PATIENT_NAME$")
    value: str = Field(min_length=1, max_length=128)


class StructuredDocumentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1, max_length=128)
    client_document_id: str = Field(min_length=1, max_length=128)
    role: DocumentRole
    readability: Readability
    identity_observations: tuple[IdentityObservation, ...] = Field(max_length=2)
    billed_paise: int | None = Field(default=None, ge=0)


class StructuredEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    documents: tuple[StructuredDocumentEvidence, ...] = Field(min_length=1, max_length=10)


class TriageDocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    client_document_id: str = Field(min_length=1, max_length=128)
    role: DocumentRole
    readability: Readability
    identity_observations: tuple[IdentityObservation, ...] = Field(max_length=2)


class TriageModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    documents: tuple[TriageDocumentResult, ...] = Field(min_length=1, max_length=10)
