from claims_backend.domain.adjudication import (
    ClaimCasefile,
    EvidenceFact,
    FactState,
    RuleResult,
    RuleStatus,
)
from claims_backend.domain.policy import PolicyIR
from claims_backend.domain.reconciliation import EvidenceSourceType
from claims_backend.policy.adjudicator.exceptions import UnsafeCasefileError
from claims_backend.policy.adjudicator.helpers import _result, _string


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
    candidates = {candidate.candidate_id: candidate for candidate in casefile.evidence.candidates}
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
