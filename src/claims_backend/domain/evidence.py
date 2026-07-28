from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class NormalizedRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def contained_in_page(self) -> "NormalizedRegion":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Region must be contained within the normalized page.")
        return self


class PreviewProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1, max_length=64)


class ReadabilityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Readability
    preview: PreviewProvenance


class TriageIdentityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["PATIENT_NAME"]
    value: str = Field(min_length=1, max_length=128)
    page: int = Field(ge=1)
    region: NormalizedRegion
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence: float = Field(ge=0, le=1)


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
    readability: ReadabilityObservation
    identity_observations: tuple[TriageIdentityObservation, ...] = Field(max_length=2)


class TriageModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    documents: tuple[TriageDocumentResult, ...] = Field(min_length=1, max_length=10)
