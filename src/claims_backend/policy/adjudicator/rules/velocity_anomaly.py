from claims_backend.domain.adjudication import ClaimCasefile, RuleResult, RuleStatus
from claims_backend.domain.policy import PolicyIR
from claims_backend.policy.adjudicator.helpers import _result


def _same_day_velocity_result(
    *,
    sequence: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
) -> RuleResult | None:
    prior_count = len(casefile.same_day_history)
    ordinal = prior_count + 1
    if ordinal < policy.same_day_claim_review_threshold:
        return None
    return _result(
        sequence,
        "anomaly.same_day_claim_velocity",
        RuleStatus.APPLIED,
        "SAME_DAY_CLAIM_VELOCITY",
        "/clarifications/same_day_claim_review_threshold",
        tuple(item.evidence_ref for item in casefile.same_day_history),
        {
            "prior_same_day_claims": prior_count,
            "claim_ordinal": ordinal,
            "review_threshold": policy.same_day_claim_review_threshold,
            "operation": "REVIEW_SIGNAL",
        },
        amount,
        0,
    )
