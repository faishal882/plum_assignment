from datetime import timedelta

from claims_backend.domain.adjudication import ClaimCasefile, FactState, RuleResult, RuleStatus
from claims_backend.domain.policy import PolicyIR
from claims_backend.policy.adjudicator.helpers import _iso_date, _known_fact, _result, _string


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
