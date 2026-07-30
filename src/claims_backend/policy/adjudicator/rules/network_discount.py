from claims_backend.domain.adjudication import ClaimCasefile, FactState, RuleResult, RuleStatus
from claims_backend.domain.policy import PolicyIR
from claims_backend.policy.adjudicator.helpers import _result, _string


def _network_discount_result(
    *,
    sequence: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
    percent: int,
) -> RuleResult | None:
    provider = casefile.provider_name
    if provider is None or provider.state is not FactState.KNOWN or percent == 0:
        return None
    provider_name = _string(provider.value)
    network_names = {name.casefold(): name for name in policy.network_hospitals}
    matched = network_names.get(provider_name.casefold())
    if matched is None:
        return None
    deduction = amount * percent // 100
    return _result(
        sequence,
        f"amount.{casefile.category.casefold()}.network_discount",
        RuleStatus.APPLIED,
        "NETWORK_DISCOUNT_APPLIED",
        f"{policy.category_rules[casefile.category].source_pointer}/network_discount_percent",
        (*provider.evidence_refs, *casefile.billed_paise.evidence_refs),
        {
            "provider_name": matched,
            "network_discount_percent": percent,
            "eligible_paise": amount,
            "operation": "PERCENT_DISCOUNT",
        },
        amount,
        -deduction,
    )
