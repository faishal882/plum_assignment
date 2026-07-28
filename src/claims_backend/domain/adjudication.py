import json
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

type JsonScalar = str | int | bool | None
type EvidenceValue = JsonScalar | list[str]


class FactState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class RuleStatus(StrEnum):
    PASS = "PASS"
    APPLIED = "APPLIED"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class AdjudicationRecommendation(StrEnum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class EvidenceFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: FactState
    value: EvidenceValue
    evidence_refs: tuple[str, ...]


class ClaimCasefile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    claim_id: UUID
    claim_version: int = Field(ge=1)
    member_id: str
    member_version_id: UUID
    policy_version_id: UUID
    category: str
    claimed_paise: int = Field(ge=0)
    currency: str
    eligibility: EvidenceFact
    document_roles: EvidenceFact
    billed_paise: EvidenceFact
    ytd_used_paise: EvidenceFact

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()

    def canonical_hash(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


class RuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    rule_id: str
    status: RuleStatus
    reason_code: str
    policy_path: str
    evidence_refs: tuple[str, ...]
    inputs: dict[str, JsonScalar | list[str]]
    amount_before_paise: int
    adjustment_paise: int
    amount_after_paise: int


class AdjudicationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation: AdjudicationRecommendation
    approved_paise: int = Field(ge=0)
    currency: str
    casefile_hash: str
    policy_ir_sha256: str
    rule_results: tuple[RuleResult, ...]
    canonical_hash: str
