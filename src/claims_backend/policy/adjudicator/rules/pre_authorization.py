from claims_backend.domain.adjudication import ClaimCasefile, FactState, RuleResult, RuleStatus
from claims_backend.domain.policy import PolicyIR, PreAuthorizationMode
from claims_backend.policy.adjudicator.exceptions import UnsafeCasefileError
from claims_backend.policy.adjudicator.helpers import (
    _integer,
    _iso_date,
    _known_fact,
    _result,
    _string,
)


def _pre_authorization_result(
    *,
    sequence: int,
    casefile: ClaimCasefile,
    policy: PolicyIR,
    amount: int,
    roles: set[str],
) -> RuleResult | None:
    treatment_fact = casefile.clinical_treatment
    if treatment_fact is None or treatment_fact.state is not FactState.KNOWN:
        return None
    treatment = _string(treatment_fact.value).upper()
    rule = policy.pre_authorization_rules.get(treatment)
    if rule is None or rule.mode is PreAuthorizationMode.NEVER:
        return None
    required = rule.mode is PreAuthorizationMode.ALWAYS or (
        rule.mode is PreAuthorizationMode.ABOVE_THRESHOLD
        and rule.threshold_paise is not None
        and amount > rule.threshold_paise
    )
    if not required:
        return None
    present, authorization_refs = _valid_pre_authorization(
        casefile,
        treatment=treatment,
        amount=amount,
        role_present="PRE_AUTHORIZATION" in roles,
    )
    return _result(
        sequence,
        rule.rule_id,
        RuleStatus.PASS if present else RuleStatus.FAIL,
        "PRE_AUTH_PRESENT" if present else "PRE_AUTH_MISSING",
        rule.source_pointer,
        (
            *treatment_fact.evidence_refs,
            *casefile.billed_paise.evidence_refs,
            *authorization_refs,
        ),
        {
            "treatment": treatment,
            "eligible_paise": amount,
            "mode": rule.mode.value,
            "threshold_paise": rule.threshold_paise,
            "authorization_present": present,
        },
        amount,
        0 if present else -amount,
    )


def _valid_pre_authorization(
    casefile: ClaimCasefile,
    *,
    treatment: str,
    amount: int,
    role_present: bool,
) -> tuple[bool, tuple[str, ...]]:
    authorization = casefile.pre_authorization
    if authorization is None:
        return False, ()
    facts = (
        authorization.patient_name,
        authorization.treatment,
        authorization.valid_from,
        authorization.valid_to,
        authorization.reference,
        authorization.applicable_paise,
    )
    if any(fact.state is not FactState.KNOWN for fact in facts):
        raise UnsafeCasefileError("Pre-authorization facts must be reconciled.")
    treatment_date = _iso_date(
        _known_fact(casefile.treatment_date, "treatment date").value,
        "treatment date",
    )
    valid_from = _iso_date(authorization.valid_from.value, "authorization valid from")
    valid_to = _iso_date(authorization.valid_to.value, "authorization valid to")
    patient = _string(_known_fact(casefile.patient_identity, "patient identity").value).casefold()
    matches = (
        role_present
        and _string(authorization.patient_name.value).casefold() == patient
        and _string(authorization.treatment.value).upper() == treatment
        and valid_from <= treatment_date <= valid_to
        and _integer(authorization.applicable_paise.value) >= amount
    )
    return matches, tuple(reference for fact in facts for reference in fact.evidence_refs)
