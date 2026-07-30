from claims_backend.domain.adjudication import (
    AdjudicationProposal,
    AdjudicationRecommendation,
    ClaimCasefile,
    FactState,
    RuleResult,
    RuleStatus,
)
from claims_backend.domain.policy import LimitOutcome, PolicyIR
from claims_backend.policy.adjudicator.exceptions import UnsafeCasefileError
from claims_backend.policy.adjudicator.helpers import (
    _integer,
    _proposal,
    _result,
    _string_list,
)
from claims_backend.policy.adjudicator.rules import (
    _clinical_exclusion_result,
    _evaluate_dental_line_items,
    _network_discount_result,
    _pre_authorization_result,
    _same_day_velocity_result,
    _waiting_period_result,
)


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
        pre_authorization_result = _pre_authorization_result(
            sequence=len(results) + 1,
            casefile=casefile,
            policy=policy,
            amount=amount,
            roles=roles,
        )
        if pre_authorization_result is not None:
            results.append(pre_authorization_result)
            if pre_authorization_result.status is RuleStatus.FAIL:
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
            if policy.limit_exceeded_outcome is not LimitOutcome.REJECT:
                raise UnsafeCasefileError(
                    "Configured category limit outcome is not supported by this evaluator."
                )
            results.append(
                _result(
                    len(results) + 1,
                    f"amount.{casefile.category.casefold()}.category_limit",
                    RuleStatus.FAIL,
                    "PER_CLAIM_EXCEEDED",
                    f"{category.source_pointer}/sub_limit",
                    casefile.billed_paise.evidence_refs,
                    {
                        "eligible_paise": amount,
                        "limit_paise": category.limit_paise,
                        "general_limit_paise": policy.general_per_claim_limit_paise,
                        "precedence": policy.limit_precedence.value,
                        "outcome": policy.limit_exceeded_outcome.value,
                        "operation": "LIMIT_COMPARE",
                    },
                    amount,
                    -amount,
                )
            )
            return _proposal(
                AdjudicationRecommendation.REJECTED,
                0,
                casefile,
                policy,
                results,
            )
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
                    "operation": "LIMIT_COMPARE",
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
                    "operation": "LIMIT_COMPARE",
                },
                amount,
                0,
            )
        )
        network_discount = _network_discount_result(
            sequence=len(results) + 1,
            casefile=casefile,
            policy=policy,
            amount=amount,
            percent=category.network_discount_percent,
        )
        if network_discount is not None:
            results.append(network_discount)
            amount = network_discount.amount_after_paise
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
                    "operation": "PERCENT_COPAY",
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
        anomaly = _same_day_velocity_result(
            sequence=len(results) + 1,
            casefile=casefile,
            policy=policy,
            amount=approved,
        )
        if anomaly is not None:
            results.append(anomaly)
        results.append(
            _result(
                len(results) + 1,
                "final.recommendation",
                RuleStatus.APPLIED,
                f"FINAL_{recommendation.value}",
                "/rule_order/final_recommendation",
                casefile.billed_paise.evidence_refs,
                {
                    "operation": "FINAL_RECOMMENDATION",
                    "recommendation": recommendation.value,
                },
                approved,
                0,
            )
        )
        return _proposal(
            recommendation,
            approved,
            casefile,
            policy,
            results,
        )
