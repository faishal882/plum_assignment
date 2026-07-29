from enum import StrEnum
from typing import Annotated, Literal

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


ObservationId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class TriageIdentitySelection(BaseModel):
    """A semantic identity value grounded to one backend-generated OCR observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["PATIENT_NAME"] = "PATIENT_NAME"
    value: str = Field(min_length=1, max_length=128)
    observation_id: ObservationId


class TriageDocumentPrediction(BaseModel):
    """Untrusted semantic triage output; provenance is represented only by opaque references."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_document_id: str = Field(min_length=1, max_length=128)
    role: DocumentRole
    role_evidence_refs: tuple[ObservationId, ...] = Field(min_length=1, max_length=20)
    readability: Readability
    readability_evidence_refs: tuple[ObservationId, ...] = Field(
        min_length=1,
        max_length=20,
    )
    identity_observations: tuple[TriageIdentitySelection, ...] = Field(max_length=2)


class TriageModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[3] = 3
    documents: tuple[TriageDocumentPrediction, ...] = Field(min_length=1, max_length=10)


class TriageProviderDocumentPredictionV4(BaseModel):
    """Tolerant provider wire contract for semantic triage predictions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_document_id: str = Field(min_length=1, max_length=128)
    role: DocumentRole
    role_evidence_refs: tuple[ObservationId, ...] = Field(min_length=1, max_length=100)
    readability: Readability
    readability_evidence_refs: tuple[ObservationId, ...] = Field(
        min_length=1,
        max_length=100,
    )
    identity_observations: tuple[TriageIdentitySelection, ...] = Field(max_length=2)


class TriageProviderOutputV4(BaseModel):
    """Provider-facing v4 contract; this is not the canonical triage result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[4] = 4
    documents: tuple[TriageProviderDocumentPredictionV4, ...] = Field(min_length=1, max_length=10)


class TriageEvidenceField(StrEnum):
    ROLE = "ROLE"
    READABILITY = "READABILITY"


class TriageEvidenceNormalizationCode(StrEnum):
    DEDUPLICATED = "TRIAGE_EVIDENCE_REFS_DEDUPLICATED"
    TRUNCATED = "TRIAGE_EVIDENCE_REFS_TRUNCATED"


class TriageEvidenceFieldNormalization(BaseModel):
    """Bounded audit result for one provider-supplied evidence-reference field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: TriageEvidenceField
    received_refs: tuple[ObservationId, ...] = Field(min_length=1, max_length=100)
    unique_refs: tuple[ObservationId, ...] = Field(min_length=1, max_length=100)
    retained_refs: tuple[ObservationId, ...] = Field(min_length=1, max_length=5)
    duplicate_dropped_refs: tuple[ObservationId, ...] = Field(max_length=99)
    over_citation_dropped_refs: tuple[ObservationId, ...] = Field(max_length=95)
    codes: tuple[TriageEvidenceNormalizationCode, ...] = Field(max_length=2)


class TriageEvidenceNormalizationReport(BaseModel):
    """Durable deterministic explanation of v4 evidence-reference normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1, max_length=64)
    role: TriageEvidenceFieldNormalization
    readability: TriageEvidenceFieldNormalization


class TriageIdentityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["PATIENT_NAME"]
    value: str = Field(min_length=1, max_length=128)
    observation_id: ObservationId | None = None
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
    treatment_date: str | None = None
    clinical_condition: str | None = None
    clinical_treatment: str | None = None
    provider_name: str | None = None
    line_items_paise: dict[str, int] = Field(default_factory=dict)


class StructuredEvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    documents: tuple[StructuredDocumentEvidence, ...] = Field(min_length=1, max_length=10)


class TriageDocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    client_document_id: str = Field(min_length=1, max_length=128)
    role: DocumentRole
    role_evidence_refs: tuple[ObservationId, ...] = ()
    readability: ReadabilityObservation
    readability_evidence_refs: tuple[ObservationId, ...] = ()
    identity_observations: tuple[TriageIdentityObservation, ...] = Field(max_length=2)


class ResolvedTriageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[3] = 3
    documents: tuple[TriageDocumentResult, ...] = Field(min_length=1, max_length=10)
