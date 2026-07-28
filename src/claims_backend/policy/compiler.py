import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from claims_backend.domain.policy import (
    CategoryRule,
    DentalProcedureRule,
    DocumentRequirementRule,
    FindingCategory,
    LimitOutcome,
    LimitPrecedence,
    PolicyFinding,
    PolicyFindingSeverity,
    PolicyIR,
    PreAuthorizationMode,
    PreAuthorizationRule,
    WaitingPeriodRule,
    WaitingPeriodRules,
)

COMPILER_VERSION = "policy-compiler-v3"
_TEST_IDENTIFIER_PATTERN = re.compile(r"\bTC\d+\b|case_id|test_case", re.IGNORECASE)


class _FamilyFloater(BaseModel):
    model_config = ConfigDict(extra="allow")

    covered_relationships: list[str]


class _Coverage(BaseModel):
    model_config = ConfigDict(extra="allow")

    annual_opd_limit: int = Field(ge=0)
    per_claim_limit: int = Field(ge=0)
    family_floater: _FamilyFloater


class _PolicyHolder(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_start_date: str
    policy_end_date: str


class _CategorySource(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub_limit: int = Field(ge=0)
    copay_percent: int = Field(ge=0, le=100)
    network_discount_percent: int = Field(default=0, ge=0, le=100)
    requires_prescription: bool
    requires_pre_auth: bool = False
    covered: bool
    requires_dental_report: bool = False
    covered_procedures: list[str] = Field(default_factory=list)
    excluded_procedures: list[str] = Field(default_factory=list)


class _DocumentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str]
    optional: list[str]


class _SubmissionRules(BaseModel):
    model_config = ConfigDict(extra="allow")

    currency: Literal["INR"]


class _WaitingPeriods(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial_waiting_period_days: int = Field(ge=0)
    pre_existing_conditions_days: int = Field(ge=0)
    specific_conditions: dict[str, int]


class _PolicySource(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_id: str = Field(min_length=1, max_length=64)
    policy_holder: _PolicyHolder
    coverage: _Coverage
    opd_categories: dict[str, _CategorySource]
    document_requirements: dict[str, _DocumentSource]
    submission_rules: _SubmissionRules
    waiting_periods: _WaitingPeriods


class _Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["APPROVED"]
    approved_by: str = Field(min_length=1, max_length=128)
    approved_at: datetime


class _PreAuthorizationClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: PreAuthorizationMode
    threshold_rupees: int | None = Field(default=None, ge=0)


class _Clarifications(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit_precedence: LimitPrecedence
    limit_exceeded_outcome: LimitOutcome
    category_limits_rupees: dict[str, int]
    dental_report_evidence: Literal["DETAILED_LINE_ITEM_BILL_OR_DENTAL_REPORT"]
    pre_authorization: dict[str, _PreAuthorizationClarification]
    relationship_aliases: dict[str, str]


class _Overlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    overlay_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    base_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approval: _Approval
    clarifications: _Clarifications


@dataclass(frozen=True, slots=True)
class PolicyCompilation:
    source_sha256: str
    overlay_sha256: str
    overlay_id: str | None
    overlay_version: int | None
    overlay_base_policy_sha256: str | None
    overlay_approved_by: str | None
    overlay_approved_at: datetime | None
    ir: PolicyIR | None
    canonical_ir: bytes | None
    ir_sha256: str | None
    findings: tuple[PolicyFinding, ...]

    @property
    def has_errors(self) -> bool:
        return any(finding.severity is PolicyFindingSeverity.ERROR for finding in self.findings)


class PolicyCompiler:
    def compile(self, source_bytes: bytes, overlay_bytes: bytes) -> PolicyCompilation:
        source_hash = sha256(source_bytes).hexdigest()
        overlay_hash = sha256(overlay_bytes).hexdigest()
        try:
            source = _PolicySource.model_validate_json(source_bytes)
            overlay = _Overlay.model_validate_json(overlay_bytes)
        except ValidationError as error:
            return _invalid_compilation(source_hash, overlay_hash, error)

        findings: list[PolicyFinding] = []
        if overlay.base_policy_sha256 != source_hash:
            findings.append(
                PolicyFinding(
                    category=FindingCategory.REFERENTIAL,
                    severity=PolicyFindingSeverity.ERROR,
                    code="OVERLAY_BASE_POLICY_MISMATCH",
                    source_pointer="/base_policy_sha256",
                    message="Overlay base hash does not identify this policy source.",
                )
            )
        if _TEST_IDENTIFIER_PATTERN.search(overlay_bytes.decode("utf-8")):
            findings.append(
                PolicyFinding(
                    category=FindingCategory.SEMANTIC,
                    severity=PolicyFindingSeverity.ERROR,
                    code="TEST_IDENTIFIER_FORBIDDEN",
                    source_pointer="/",
                    message="Policy overlays cannot contain evaluation-case identifiers.",
                )
            )
        findings.extend(_semantic_findings(source, overlay))
        if any(finding.severity is PolicyFindingSeverity.ERROR for finding in findings):
            return PolicyCompilation(
                source_sha256=source_hash,
                overlay_sha256=overlay_hash,
                overlay_id=overlay.overlay_id,
                overlay_version=overlay.version,
                overlay_base_policy_sha256=overlay.base_policy_sha256,
                overlay_approved_by=overlay.approval.approved_by,
                overlay_approved_at=overlay.approval.approved_at,
                ir=None,
                canonical_ir=None,
                ir_sha256=None,
                findings=tuple(findings),
            )

        ir = _build_ir(source, overlay, source_hash, overlay_hash)
        canonical_ir = json.dumps(
            ir.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return PolicyCompilation(
            source_sha256=source_hash,
            overlay_sha256=overlay_hash,
            overlay_id=overlay.overlay_id,
            overlay_version=overlay.version,
            overlay_base_policy_sha256=overlay.base_policy_sha256,
            overlay_approved_by=overlay.approval.approved_by,
            overlay_approved_at=overlay.approval.approved_at,
            ir=ir,
            canonical_ir=canonical_ir,
            ir_sha256=sha256(canonical_ir).hexdigest(),
            findings=tuple(findings),
        )


def _invalid_compilation(
    source_hash: str,
    overlay_hash: str,
    error: ValidationError,
) -> PolicyCompilation:
    findings = tuple(
        PolicyFinding(
            category=FindingCategory.SCHEMA,
            severity=PolicyFindingSeverity.ERROR,
            code="SCHEMA_VALIDATION_FAILED",
            source_pointer="/" + "/".join(str(part) for part in issue["loc"]),
            message=issue["msg"],
        )
        for issue in error.errors(include_url=False)
    )
    return PolicyCompilation(
        source_sha256=source_hash,
        overlay_sha256=overlay_hash,
        overlay_id=None,
        overlay_version=None,
        overlay_base_policy_sha256=None,
        overlay_approved_by=None,
        overlay_approved_at=None,
        ir=None,
        canonical_ir=None,
        ir_sha256=None,
        findings=findings,
    )


def _semantic_findings(
    source: _PolicySource,
    overlay: _Overlay,
) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []
    aliases = overlay.clarifications.relationship_aliases
    for index, relationship in enumerate(source.coverage.family_floater.covered_relationships):
        if relationship in aliases:
            findings.append(
                PolicyFinding(
                    category=FindingCategory.VOCABULARY,
                    severity=PolicyFindingSeverity.WARNING,
                    code="RELATIONSHIP_ALIAS_NORMALIZED",
                    source_pointer=(f"/coverage/family_floater/covered_relationships/{index}"),
                    message=f"{relationship} is normalized to {aliases[relationship]}.",
                    resolved_by_overlay=True,
                )
            )

    consultation = source.opd_categories.get("consultation")
    consultation_override = overlay.clarifications.category_limits_rupees.get("CONSULTATION")
    if (
        consultation is not None
        and consultation_override is not None
        and consultation.sub_limit != consultation_override
    ):
        findings.append(
            PolicyFinding(
                category=FindingCategory.CONTRADICTION,
                severity=PolicyFindingSeverity.WARNING,
                code="CATEGORY_LIMIT_OVERRIDDEN",
                source_pointer="/opd_categories/consultation/sub_limit",
                message="The approved overlay replaces the consultation source limit.",
                resolved_by_overlay=True,
            )
        )

    diagnostic = source.opd_categories.get("diagnostic")
    if diagnostic is not None and not diagnostic.requires_pre_auth:
        findings.append(
            PolicyFinding(
                category=FindingCategory.SEMANTIC,
                severity=PolicyFindingSeverity.WARNING,
                code="GENERIC_PREAUTH_FLAG_OVERRIDDEN",
                source_pointer="/opd_categories/diagnostic/requires_pre_auth",
                message="Specific approved diagnostic rules override the generic false flag.",
                resolved_by_overlay=True,
            )
        )

    dental = source.opd_categories.get("dental")
    dental_documents = source.document_requirements.get("DENTAL")
    if (
        dental is not None
        and dental.requires_dental_report
        and dental_documents is not None
        and "DENTAL_REPORT" not in dental_documents.required
    ):
        findings.append(
            PolicyFinding(
                category=FindingCategory.REFERENTIAL,
                severity=PolicyFindingSeverity.WARNING,
                code="DENTAL_EVIDENCE_RECONCILED",
                source_pointer="/document_requirements/DENTAL",
                message="Approved alternative evidence resolves the dental report mismatch.",
                resolved_by_overlay=True,
            )
        )
    return findings


def _build_ir(
    source: _PolicySource,
    overlay: _Overlay,
    source_hash: str,
    overlay_hash: str,
) -> PolicyIR:
    category_rules: dict[str, CategoryRule] = {}
    for source_name, category in source.opd_categories.items():
        category_name = source_name.upper()
        limit_rupees = overlay.clarifications.category_limits_rupees.get(
            category_name,
            category.sub_limit,
        )
        category_rules[category_name] = CategoryRule(
            rule_id=f"category.{source_name}.amount",
            source_pointer=f"/opd_categories/{source_name}",
            limit_paise=limit_rupees * 100,
            copay_percent=category.copay_percent,
            network_discount_percent=category.network_discount_percent,
            requires_prescription=category.requires_prescription,
            covered=category.covered,
        )

    document_rules = {
        category: DocumentRequirementRule(
            rule_id=f"documents.{category.casefold()}",
            source_pointer=f"/document_requirements/{category}",
            required=tuple(requirements.required),
            optional=tuple(requirements.optional),
            alternative_evidence=(
                overlay.clarifications.dental_report_evidence if category == "DENTAL" else None
            ),
        )
        for category, requirements in source.document_requirements.items()
    }
    pre_authorization_rules = {
        name: PreAuthorizationRule(
            rule_id=f"pre_authorization.{name.casefold()}",
            source_pointer=f"/clarifications/pre_authorization/{name}",
            mode=rule.mode,
            threshold_paise=(
                None if rule.threshold_rupees is None else rule.threshold_rupees * 100
            ),
        )
        for name, rule in overlay.clarifications.pre_authorization.items()
    }
    waiting_period_rules = WaitingPeriodRules(
        initial=WaitingPeriodRule(
            rule_id="waiting_period.initial",
            source_pointer="/waiting_periods/initial_waiting_period_days",
            days=source.waiting_periods.initial_waiting_period_days,
        ),
        pre_existing=WaitingPeriodRule(
            rule_id="waiting_period.pre_existing",
            source_pointer="/waiting_periods/pre_existing_conditions_days",
            days=source.waiting_periods.pre_existing_conditions_days,
        ),
        specific_conditions={
            condition: WaitingPeriodRule(
                rule_id=f"waiting_period.specific_condition.{condition}",
                source_pointer=f"/waiting_periods/specific_conditions/{condition}",
                days=days,
            )
            for condition, days in sorted(
                source.waiting_periods.specific_conditions.items()
            )
        },
    )
    dental_source = source.opd_categories.get("dental")
    dental_procedure_rules: dict[str, DentalProcedureRule] = {}
    if dental_source is not None:
        for covered, procedures, pointer in (
            (
                True,
                dental_source.covered_procedures,
                "/opd_categories/dental/covered_procedures",
            ),
            (
                False,
                dental_source.excluded_procedures,
                "/opd_categories/dental/excluded_procedures",
            ),
        ):
            for index, label in enumerate(procedures):
                concept = _concept(label)
                dental_procedure_rules[concept] = DentalProcedureRule(
                    rule_id=f"dental.procedure.{concept}",
                    source_pointer=f"{pointer}/{index}",
                    concept=concept,
                    label=label,
                    covered=covered,
                )
    return PolicyIR(
        schema_version=3,
        policy_id=source.policy_id,
        source_sha256=source_hash,
        overlay_sha256=overlay_hash,
        overlay_id=overlay.overlay_id,
        overlay_version=overlay.version,
        effective_from=source.policy_holder.policy_start_date,
        effective_to=source.policy_holder.policy_end_date,
        currency=source.submission_rules.currency,
        general_per_claim_limit_paise=source.coverage.per_claim_limit * 100,
        annual_opd_limit_paise=source.coverage.annual_opd_limit * 100,
        limit_precedence=overlay.clarifications.limit_precedence,
        limit_exceeded_outcome=overlay.clarifications.limit_exceeded_outcome,
        category_rules=category_rules,
        document_requirements=document_rules,
        pre_authorization_rules=pre_authorization_rules,
        waiting_period_rules=waiting_period_rules,
        dental_procedure_rules=dental_procedure_rules,
        relationship_aliases=overlay.clarifications.relationship_aliases,
        rule_order=(
            "eligibility",
            "evidence_sufficiency",
            "waiting_periods",
            "exclusions",
            "pre_authorization",
            "network_discount",
            "category_limit",
            "annual_and_family_limit",
            "copay",
            "final_recommendation",
        ),
        engine_contract_version="policy-evaluator-v3",
    )


def _concept(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.casefold())).strip("_")
