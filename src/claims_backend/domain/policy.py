from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FindingCategory(StrEnum):
    SCHEMA = "SCHEMA"
    SEMANTIC = "SEMANTIC"
    REFERENTIAL = "REFERENTIAL"
    VOCABULARY = "VOCABULARY"
    CONTRADICTION = "CONTRADICTION"


class PolicyFindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LimitPrecedence(StrEnum):
    CATEGORY_OVER_GENERAL = "CATEGORY_OVER_GENERAL"


class LimitOutcome(StrEnum):
    REJECT = "REJECT"
    CAP = "CAP"
    REVIEW = "REVIEW"


class PreAuthorizationMode(StrEnum):
    ABOVE_THRESHOLD = "ABOVE_THRESHOLD"
    ALWAYS = "ALWAYS"
    NEVER = "NEVER"


class PolicyVersionStatus(StrEnum):
    INVALID = "INVALID"
    COMPILED = "COMPILED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PolicyFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: FindingCategory
    severity: PolicyFindingSeverity
    code: str
    source_pointer: str
    message: str
    resolved_by_overlay: bool = False


class CategoryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    limit_paise: int
    copay_percent: int
    network_discount_percent: int
    requires_prescription: bool
    covered: bool


class DocumentRequirementRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    required: tuple[str, ...]
    optional: tuple[str, ...]
    alternative_evidence: str | None = None


class PreAuthorizationRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    mode: PreAuthorizationMode
    threshold_paise: int | None
    evidence_required: bool = True


class WaitingPeriodRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    days: int = Field(ge=0)


class WaitingPeriodRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial: WaitingPeriodRule
    pre_existing: WaitingPeriodRule
    specific_conditions: dict[str, WaitingPeriodRule]


class DentalProcedureRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    concept: str
    label: str
    covered: bool


class ClinicalExclusionRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    source_pointer: str
    concept: str
    label: str


class PolicyIR(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    policy_id: str
    source_sha256: str
    overlay_sha256: str
    overlay_id: str
    overlay_version: int
    effective_from: str
    effective_to: str
    currency: str
    general_per_claim_limit_paise: int
    annual_opd_limit_paise: int
    limit_precedence: LimitPrecedence
    limit_exceeded_outcome: LimitOutcome
    category_rules: dict[str, CategoryRule]
    document_requirements: dict[str, DocumentRequirementRule]
    pre_authorization_rules: dict[str, PreAuthorizationRule]
    waiting_period_rules: WaitingPeriodRules
    dental_procedure_rules: dict[str, DentalProcedureRule]
    clinical_exclusion_rules: dict[str, ClinicalExclusionRule]
    relationship_aliases: dict[str, str]
    rule_order: tuple[str, ...]
    engine_contract_version: str


@dataclass(frozen=True, slots=True)
class PolicyVersionInspection:
    policy_version_id: UUID
    policy_id: str
    version: int
    source_sha256: str
    overlay_sha256: str
    overlay_id: str | None
    overlay_version: int | None
    compiler_version: str
    ir_sha256: str | None
    status: PolicyVersionStatus
    findings: tuple[PolicyFinding, ...]
    compiled_at: datetime
    activated_at: datetime | None
    activated_by: str | None


@dataclass(frozen=True, slots=True)
class PolicyActivationEvent:
    id: UUID
    policy_version_id: UUID
    actor: str
    from_status: PolicyVersionStatus
    to_status: PolicyVersionStatus
    ir_sha256: str
    created_at: datetime
