from claims_backend.domain.adjudication import ClaimCasefile, RuleResult, RuleStatus
from claims_backend.domain.policy import PolicyIR
from claims_backend.policy.adjudicator.exceptions import UnsafeCasefileError
from claims_backend.policy.adjudicator.helpers import _result


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
        reason_code = "DENTAL_LINE_ITEM_COVERED" if rule.covered else "DENTAL_LINE_ITEM_EXCLUDED"
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
