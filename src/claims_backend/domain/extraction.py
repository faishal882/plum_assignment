from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelRoute(StrEnum):
    FAST_TRIAGE = "FAST_TRIAGE"
    COMPLEX_EXTRACTION = "COMPLEX_EXTRACTION"


JsonScalar = str | int | float | bool | None


class UntrustedEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_path: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Canonical fact path beginning with billing., clinical., document., "
            "patient., or treatment."
        ),
    )
    value: JsonScalar
    normalized_value: JsonScalar = None
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)


class ComplexExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["complex-extraction-v1"]
    candidates: tuple[UntrustedEvidenceCandidate, ...] = Field(max_length=100)


class EvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_path: str
    value: JsonScalar
    normalized_value: JsonScalar
    evidence_refs: tuple[str, ...]
    confidence: float
    producer: Literal["BEDROCK"] = "BEDROCK"
    model_id: str
    route: ModelRoute
    prompt_version: str
    schema_version: str


class ModelValidationError(Exception):
    code = "MODEL_VALIDATION_FAILED"


class ModelAuthorityViolation(ModelValidationError):
    code = "MODEL_AUTHORITY_VIOLATION"


class ModelSchemaValidationError(ModelValidationError):
    code = "MODEL_SCHEMA_VALIDATION_FAILED"


class ModelSemanticValidationError(ModelValidationError):
    code = "MODEL_SEMANTIC_VALIDATION_FAILED"


class ModelGroundingValidationError(ModelValidationError):
    code = "MODEL_GROUNDING_VALIDATION_FAILED"
