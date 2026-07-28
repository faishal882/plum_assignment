from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from claims_backend.domain.evidence import NormalizedRegion


class TextractProfile(StrEnum):
    EXPENSE = "EXPENSE"
    FORMS_TABLES = "FORMS_TABLES"
    TEXT = "TEXT"


class OcrObservationKind(StrEnum):
    LINE = "LINE"
    WORD = "WORD"
    EXPENSE_FIELD = "EXPENSE_FIELD"


class OcrObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_version_id: UUID
    page_number: int = Field(ge=1)
    kind: OcrObservationKind
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    region: NormalizedRegion
    source_id: str = Field(min_length=1, max_length=128)


class OcrPageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: TextractProfile
    provider_request_id: str = Field(min_length=1, max_length=128)
    retry_attempts: int = Field(ge=0)
    observations: tuple[OcrObservation, ...]


class OcrError(Exception):
    code = "OCR_FAILED"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        provider_code: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        if retryable is not None:
            self.retryable = retryable
        self.provider_code = provider_code
        self.provider_request_id = provider_request_id
        super().__init__(message)


class OcrMalformedResponseError(OcrError):
    code = "TEXTRACT_MALFORMED_RESPONSE"


class OcrThrottledError(OcrError):
    code = "TEXTRACT_THROTTLED"
    retryable = True


class OcrTimeoutError(OcrError):
    code = "TEXTRACT_TIMEOUT"
    retryable = True


class OcrProviderError(OcrError):
    code = "TEXTRACT_PROVIDER_ERROR"
