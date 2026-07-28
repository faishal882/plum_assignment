import unicodedata
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from claims_backend.domain.evidence import NormalizedRegion


class IdentityState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class IdentityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    producer: str = Field(min_length=1, max_length=64)
    producer_version: str = Field(min_length=1, max_length=64)
    client_document_id: str = Field(min_length=1, max_length=128)
    document_version_id: UUID
    page: int = Field(ge=1)
    region: NormalizedRegion
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence: float = Field(ge=0, le=1)
    value: str = Field(min_length=1, max_length=128)


class ReconciledIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: IdentityState
    member_name: str = Field(min_length=1, max_length=128)
    candidates: tuple[IdentityCandidate, ...]


def reconcile_patient_identity(
    member_name: str,
    candidates: tuple[IdentityCandidate, ...],
) -> ReconciledIdentity:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.client_document_id,
                str(item.document_version_id),
                item.page,
                item.source_text_sha256,
            ),
        )
    )
    if not ordered:
        state = IdentityState.UNKNOWN
    else:
        values = {_normalize(item.value) for item in ordered}
        state = (
            IdentityState.KNOWN
            if values == {_normalize(member_name)}
            else IdentityState.CONFLICT
        )
    return ReconciledIdentity(
        state=state,
        member_name=member_name,
        candidates=ordered,
    )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()
