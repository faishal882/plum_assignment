import json
from datetime import date, timedelta
from hashlib import sha256

from claims_backend.domain.adjudication import (
    AdjudicationProposal,
    AdjudicationRecommendation,
    ClaimCasefile,
    EvidenceFact,
    FactState,
    RuleResult,
    RuleStatus,
)
from claims_backend.domain.policy import PolicyIR
from claims_backend.domain.reconciliation import EvidenceSourceType


class UnsafeCasefileError(ValueError):
    pass


class DeterministicPolicyAdjudicator:
    def evaluate(
        self,
        casefile: ClaimCasefile,
        policy: PolicyIR,
    ) -> AdjudicationProposal:
        if casefile.policy_version_id is None or casefile.category not in policy.category_rules:
            raise UnsafeCasefileError
        if casefile.currency != policy.currency:
            raise UnsafeCasefileError
        for fact in (
            casefile.eligibility,
            casefile.document_roles,
            casefile.billed_paise,
            casefile.ytd_used_paise,
        ):
            if fact.state is not FactState.KNOWN:
                raise UnsafeCasefileError("Critical facts must be known before adjudication.")

        category = policy.category_rules[casefile.category]
        amount = casefile.claimed_paise
        results: list[RuleResult] = []
        results.append(
            _result(
                len(results) + 1,
                "eligibility.member_active",
                RuleStatus.PASS,
                "MEMBER_ELIGIBLE",
                "/coverage/family_floater",
                casefile.eligibility.evidence_refs,
                {"eligible": True},
                amount,
                0,
            )
        )
        roles = set(_string_list(casefile.document_roles.value))
        required = set(policy.document_requirements[casefile.category].required)
        missing = sorted(required - roles)
        if missing:
            raise UnsafeCasefileError("Required evidence is missing.")
        results.append(
            _result(
                len(results) + 1,
                f"evidence.{casefile.category.casefold()}.required_documents",
                RuleStatus.PASS,
                "REQUIRED_DOCUMENTS_PRESENT",
                policy.document_requirements[casefile.category].source_pointer,
                casefile.document_roles.evidence_refs,
                {
                    "observed_roles": sorted(roles),
                    "required_roles": sorted(required),
                },
                amount,
                0,
            )
        )
        if casefile.schema_version >= 2:
            waiting_result = _waiting_period_result(
                sequence=len(results) + 1,
                casefile=casefile,
                policy=policy,
                amount=amount,
            )
            results.append(waiting_result)
            if waiting_result.status is RuleStatus.FAIL:
                return _proposal(
                    AdjudicationRecommendation.REJECTED,
                    0,
                    casefile,
                    policy,
                    results,
                )
        exclusion_result = _clinical_exclusion_result(
            sequence=len(results) + 1,
            casefile=casefile,
            policy=policy,
            amount=amount,
        )
        if exclusion_result is not None:
            results.append(exclusion_result)
            return _proposal(
                AdjudicationRecommendation.REJECTED,
                0,
                casefile,
                policy,
                results,
            )
        excluded_line_items = False
        if casefile.category == "DENTAL":
            amount, excluded_line_items = _evaluate_dental_line_items(
                casefile=casefile,
                policy=policy,
                amount=amount,
                results=results,
            )
        if amount > category.limit_paise:
            raise UnsafeCasefileError("Category limit outcome is not implemented for this slice.")
        results.append(
            _result(
                len(results) + 1,
                f"amount.{casefile.category.casefold()}.category_limit",
                RuleStatus.PASS,
                "WITHIN_CATEGORY_LIMIT",
                f"{category.source_pointer}/sub_limit",
                casefile.billed_paise.evidence_refs,
                {
                    "eligible_paise": amount,
                    "limit_paise": category.limit_paise,
                    "general_limit_paise": policy.general_per_claim_limit_paise,
                    "precedence": policy.limit_precedence.value,
                },
                amount,
                0,
            )
        )
        ytd_used = _integer(casefile.ytd_used_paise.value)
        remaining = max(policy.annual_opd_limit_paise - ytd_used, 0)
        if amount > remaining:
            raise UnsafeCasefileError("Annual limit outcome is not implemented for this slice.")
        results.append(
            _result(
                len(results) + 1,
                "amount.annual_opd_remaining",
                RuleStatus.PASS,
                "WITHIN_ANNUAL_OPD_REMAINING",
                "/coverage/annual_opd_limit",
                casefile.ytd_used_paise.evidence_refs,
                {
                    "ytd_used_paise": ytd_used,
                    "annual_limit_paise": policy.annual_opd_limit_paise,
                    "remaining_paise": remaining,
                },
                amount,
                0,
            )
        )
        deduction = amount * category.copay_percent // 100
        results.append(
            _result(
                len(results) + 1,
                f"amount.{casefile.category.casefold()}.copay",
                RuleStatus.APPLIED,
                "CATEGORY_COPAY_APPLIED",
                f"{category.source_pointer}/copay_percent",
                casefile.billed_paise.evidence_refs,
                {
                    "copay_percent": category.copay_percent,
                    "eligible_paise": amount,
                },
                amount,
                -deduction,
            )
        )
        approved = amount - deduction
        if not 0 <= approved <= casefile.claimed_paise:
            raise UnsafeCasefileError("Approved amount violates money invariants.")
        recommendation = (
            AdjudicationRecommendation.PARTIAL
            if excluded_line_items and approved > 0
            else AdjudicationRecommendation.REJECTED
            if approved == 0
            else AdjudicationRecommendation.APPROVED
        )
        return _proposal(
            recommendation,
            approved,
            casefile,
            policy,
            results,
        )


def _clinical_exclusion_result(
    *,
    sequence: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
) -> RuleResult | None:
    clinical_facts = (
        ("clinical.condition", casefile.clinical_condition),
        ("clinical.treatment", casefile.clinical_treatment),
    )
    for fact_path, fact in clinical_facts:
        if fact is None or fact.state is not FactState.KNOWN:
            continue
        concept = _string(fact.value).casefold()
        rule = policy.clinical_exclusion_rules.get(concept)
        if rule is None:
            continue
        _require_grounded_clinical_evidence(casefile, fact_path, fact)
        return _result(
            sequence,
            rule.rule_id,
            RuleStatus.FAIL,
            "EXCLUDED_CONDITION",
            rule.source_pointer,
            fact.evidence_refs,
            {
                "clinical_fact_path": fact_path,
                "matched_concept": concept,
                "exclusion_label": rule.label,
            },
            amount,
            -amount,
        )
    return None


def _require_grounded_clinical_evidence(
    casefile: ClaimCasefile,
    fact_path: str,
    fact: EvidenceFact,
) -> None:
    if casefile.evidence is None:
        raise UnsafeCasefileError("Clinical exclusion evidence is not grounded.")
    candidates = {
        candidate.candidate_id: candidate
        for candidate in casefile.evidence.candidates
    }
    supporting = [candidates.get(reference) for reference in fact.evidence_refs]
    if not supporting or any(candidate is None for candidate in supporting):
        raise UnsafeCasefileError("Clinical exclusion evidence is not grounded.")
    for candidate in supporting:
        if candidate is None or candidate.fact_path != fact_path:
            raise UnsafeCasefileError("Clinical exclusion evidence is not grounded.")
        if candidate.producer == "BEDROCK" and (
            not candidate.sources
            or any(
                source.source_type is not EvidenceSourceType.DOCUMENT
                for source in candidate.sources
            )
        ):
            raise UnsafeCasefileError("Clinical exclusion evidence is not grounded.")


def _evaluate_dental_line_items(
    *,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
    results: list[RuleResult],
) -> tuple[int, bool]:
    if not casefile.line_item_facts:
        raise UnsafeCasefileError("Dental procedure evidence is required.")
    if sum(item.amount_paise for item in casefile.line_item_facts) != amount:
        raise UnsafeCasefileError("Dental line items do not reconcile to the claimed amount.")
    excluded = False
    for item in casefile.line_item_facts:
        rule = policy.dental_procedure_rules.get(item.concept)
        if rule is None:
            raise UnsafeCasefileError(
                f"Dental procedure has no deterministic policy rule: {item.concept}."
            )
        adjustment = 0 if rule.covered else -item.amount_paise
        reason_code = (
            "DENTAL_LINE_ITEM_COVERED"
            if rule.covered
            else "DENTAL_LINE_ITEM_EXCLUDED"
        )
        results.append(
            _result(
                len(results) + 1,
                rule.rule_id,
                RuleStatus.PASS if rule.covered else RuleStatus.APPLIED,
                reason_code,
                rule.source_pointer,
                item.evidence_refs,
                {
                    "concept": item.concept,
                    "label": rule.label,
                    "line_item_paise": item.amount_paise,
                    "covered": rule.covered,
                },
                amount,
                adjustment,
            )
        )
        amount += adjustment
        excluded = excluded or not rule.covered
    return amount, excluded


def _waiting_period_result(
    *,
    sequence: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
) -> RuleResult:
    join_fact = _known_fact(casefile.member_join_date, "member join date")
    treatment_fact = _known_fact(casefile.treatment_date, "treatment date")
    join_date = _iso_date(join_fact.value, "member join date")
    treatment_date = _iso_date(treatment_fact.value, "treatment date")
    condition_fact = casefile.clinical_condition
    condition = (
        ""
        if condition_fact is None or condition_fact.state is not FactState.KNOWN
        else _string(condition_fact.value).casefold()
    )
    rule = policy.waiting_period_rules.specific_conditions.get(
        condition,
        policy.waiting_period_rules.initial,
    )
    eligible_from = join_date + timedelta(days=rule.days)
    waiting = treatment_date < eligible_from
    return _result(
        sequence,
        rule.rule_id,
        RuleStatus.FAIL if waiting else RuleStatus.PASS,
        "WAITING_PERIOD" if waiting else "WAITING_PERIOD_SATISFIED",
        rule.source_pointer,
        (
            *join_fact.evidence_refs,
            *treatment_fact.evidence_refs,
            *(() if condition_fact is None else condition_fact.evidence_refs),
        ),
        {
            "condition": condition,
            "waiting_days": rule.days,
            "member_join_date": join_date.isoformat(),
            "treatment_date": treatment_date.isoformat(),
            "eligible_from": eligible_from.isoformat(),
        },
        amount,
        -amount if waiting else 0,
    )


def _proposal(
    recommendation: AdjudicationRecommendation,
    approved_paise: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    results: list[RuleResult],
) -> AdjudicationProposal:
    ir_bytes = json.dumps(
        policy.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    policy_hash = sha256(ir_bytes).hexdigest()
    canonical_payload = {
        "recommendation": recommendation.value,
        "approved_paise": approved_paise,
        "currency": casefile.currency,
        "casefile_hash": casefile.canonical_hash(),
        "policy_ir_sha256": policy_hash,
        "rule_results": [result.model_dump(mode="json") for result in results],
    }
    canonical_hash = sha256(
        json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return AdjudicationProposal(
        recommendation=recommendation,
        approved_paise=approved_paise,
        currency=casefile.currency,
        casefile_hash=casefile.canonical_hash(),
        policy_ir_sha256=policy_hash,
        rule_results=tuple(results),
        canonical_hash=canonical_hash,
    )


def _known_fact(fact: EvidenceFact | None, label: str) -> EvidenceFact:
    if fact is None or fact.state is not FactState.KNOWN:
        raise UnsafeCasefileError(f"{label.capitalize()} must be known before adjudication.")
    return fact


def _iso_date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(_string(value))
    except ValueError as error:
        raise UnsafeCasefileError(f"{label.capitalize()} is not a valid ISO date.") from error


def _result(
    sequence: int,
    rule_id: str,
    status: RuleStatus,
    reason_code: str,
    policy_path: str,
    evidence_refs: tuple[str, ...],
    inputs: dict[str, str | int | bool | None | list[str]],
    before: int,
    adjustment: int,
) -> RuleResult:
    return RuleResult(
        sequence=sequence,
        rule_id=rule_id,
        status=status,
        reason_code=reason_code,
        policy_path=policy_path,
        evidence_refs=evidence_refs,
        inputs=inputs,
        amount_before_paise=before,
        adjustment_paise=adjustment,
        amount_after_paise=before + adjustment,
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnsafeCasefileError
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise UnsafeCasefileError
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise UnsafeCasefileError
    return value
