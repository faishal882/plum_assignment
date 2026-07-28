import json
from hashlib import sha256

from claims_backend.domain.adjudication import (
    AdjudicationProposal,
    AdjudicationRecommendation,
    ClaimCasefile,
    FactState,
    RuleResult,
    RuleStatus,
)
from claims_backend.domain.policy import PolicyIR


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
        ir_bytes = json.dumps(
            policy.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        policy_hash = sha256(ir_bytes).hexdigest()
        canonical_payload = {
            "recommendation": AdjudicationRecommendation.APPROVED.value,
            "approved_paise": approved,
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
            recommendation=AdjudicationRecommendation.APPROVED,
            approved_paise=approved,
            currency=casefile.currency,
            casefile_hash=casefile.canonical_hash(),
            policy_ir_sha256=policy_hash,
            rule_results=tuple(results),
            canonical_hash=canonical_hash,
        )


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
