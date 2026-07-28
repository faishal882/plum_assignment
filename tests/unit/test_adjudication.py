from pathlib import Path
from uuid import UUID

from claims_backend.domain.adjudication import (
    AdjudicationRecommendation,
    ClaimCasefile,
    EvidenceFact,
    FactState,
    RuleStatus,
)
from claims_backend.policy.adjudicator import DeterministicPolicyAdjudicator
from claims_backend.policy.compiler import PolicyCompiler

POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()
OVERLAY_BYTES = Path("config/policy/assignment-overlay-v1.json").read_bytes()


def test_tc004_produces_exact_deterministic_rule_trace() -> None:
    compilation = PolicyCompiler().compile(POLICY_BYTES, OVERLAY_BYTES)
    assert compilation.ir is not None
    casefile = ClaimCasefile(
        claim_id=UUID("00000000-0000-0000-0000-000000000404"),
        claim_version=1,
        member_id="EMP001",
        member_version_id=UUID("00000000-0000-0000-0000-000000000401"),
        policy_version_id=UUID("00000000-0000-0000-0000-000000000402"),
        category="CONSULTATION",
        claimed_paise=150_000,
        currency="INR",
        eligibility=EvidenceFact(
            state=FactState.KNOWN,
            value=True,
            evidence_refs=("member-version:1",),
        ),
        document_roles=EvidenceFact(
            state=FactState.KNOWN,
            value=["PRESCRIPTION", "HOSPITAL_BILL"],
            evidence_refs=("fixture:F007", "fixture:F008"),
        ),
        billed_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=150_000,
            evidence_refs=("fixture:F008",),
        ),
        ytd_used_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=500_000,
            evidence_refs=("utilization:2024-11-01",),
        ),
    )
    adjudicator = DeterministicPolicyAdjudicator()

    first = adjudicator.evaluate(casefile, compilation.ir)
    repeated = adjudicator.evaluate(casefile, compilation.ir)

    assert first.recommendation is AdjudicationRecommendation.APPROVED
    assert first.approved_paise == 135_000
    assert first.canonical_hash == repeated.canonical_hash
    assert [result.rule_id for result in first.rule_results] == [
        "eligibility.member_active",
        "evidence.consultation.required_documents",
        "amount.consultation.category_limit",
        "amount.annual_opd_remaining",
        "amount.consultation.copay",
    ]
    assert all(
        result.status in {RuleStatus.PASS, RuleStatus.APPLIED} for result in first.rule_results
    )
    assert all(result.policy_path for result in first.rule_results)
    assert all(result.evidence_refs for result in first.rule_results)
    assert all(result.inputs for result in first.rule_results)
    assert all(result.amount_before_paise is not None for result in first.rule_results)
    assert all(result.adjustment_paise is not None for result in first.rule_results)
    assert all(result.amount_after_paise is not None for result in first.rule_results)
    assert first.rule_results[-1].adjustment_paise == -15_000
    assert first.rule_results[-1].amount_after_paise == 135_000
