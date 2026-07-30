import json
from datetime import date
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
from claims_backend.policy.adjudicator.exceptions import UnsafeCasefileError


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
