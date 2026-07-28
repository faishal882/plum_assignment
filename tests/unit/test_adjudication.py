from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from hypothesis import given, settings
from hypothesis import strategies as st

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


def test_tc005_rejects_diabetes_inside_waiting_period_with_exact_eligibility_date() -> None:
    proposal = _evaluate_waiting_case(
        join_date=date(2024, 9, 1),
        treatment_date=date(2024, 10, 15),
    )

    assert proposal.recommendation is AdjudicationRecommendation.REJECTED
    assert proposal.approved_paise == 0
    waiting = proposal.rule_results[-1]
    assert waiting.status is RuleStatus.FAIL
    assert waiting.reason_code == "WAITING_PERIOD"
    assert waiting.policy_path == "/waiting_periods/specific_conditions/diabetes"
    assert waiting.inputs["eligible_from"] == "2024-11-30"
    assert waiting.evidence_refs == (
        "member:join-date",
        "claim:treatment-date",
        "document:condition",
    )


@settings(max_examples=30)
@given(join_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 9, 30)))
def test_waiting_period_boundary_day_before_day_of_and_day_after(
    join_date: date,
) -> None:
    eligible_from = join_date + timedelta(days=90)

    day_before = _evaluate_waiting_case(
        join_date=join_date,
        treatment_date=eligible_from - timedelta(days=1),
    )
    day_of = _evaluate_waiting_case(
        join_date=join_date,
        treatment_date=eligible_from,
    )
    day_after = _evaluate_waiting_case(
        join_date=join_date,
        treatment_date=eligible_from + timedelta(days=1),
    )

    assert day_before.recommendation is AdjudicationRecommendation.REJECTED
    assert day_before.rule_results[-1].reason_code == "WAITING_PERIOD"
    assert day_of.recommendation is AdjudicationRecommendation.APPROVED
    assert day_of.rule_results[2].reason_code == "WAITING_PERIOD_SATISFIED"
    assert day_after.recommendation is AdjudicationRecommendation.APPROVED
    assert day_after.rule_results[2].reason_code == "WAITING_PERIOD_SATISFIED"


def _evaluate_waiting_case(
    *,
    join_date: date,
    treatment_date: date,
):
    compilation = PolicyCompiler().compile(POLICY_BYTES, OVERLAY_BYTES)
    assert compilation.ir is not None
    casefile = ClaimCasefile(
        schema_version=2,
        claim_id=UUID("00000000-0000-0000-0000-000000000505"),
        claim_version=1,
        member_id="EMP005",
        member_version_id=UUID("00000000-0000-0000-0000-000000000501"),
        member_snapshot_sha256="5" * 64,
        policy_version_id=UUID("00000000-0000-0000-0000-000000000502"),
        category="CONSULTATION",
        claimed_paise=300_000,
        currency="INR",
        eligibility=EvidenceFact(
            state=FactState.KNOWN,
            value=True,
            evidence_refs=("member:active",),
        ),
        document_roles=EvidenceFact(
            state=FactState.KNOWN,
            value=["PRESCRIPTION", "HOSPITAL_BILL"],
            evidence_refs=("document:prescription", "document:bill"),
        ),
        billed_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=300_000,
            evidence_refs=("document:bill-total",),
        ),
        claimed_amount=EvidenceFact(
            state=FactState.KNOWN,
            value=300_000,
            evidence_refs=("claim:amount",),
        ),
        treatment_date=EvidenceFact(
            state=FactState.KNOWN,
            value=treatment_date.isoformat(),
            evidence_refs=("claim:treatment-date",),
        ),
        member_join_date=EvidenceFact(
            state=FactState.KNOWN,
            value=join_date.isoformat(),
            evidence_refs=("member:join-date",),
        ),
        patient_identity=EvidenceFact(
            state=FactState.KNOWN,
            value="vikram joshi",
            evidence_refs=("member:name", "document:name"),
        ),
        clinical_condition=EvidenceFact(
            state=FactState.KNOWN,
            value="diabetes",
            evidence_refs=("document:condition",),
        ),
        line_items=EvidenceFact(
            state=FactState.UNKNOWN,
            value=[],
            evidence_refs=(),
        ),
        ytd_used_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=0,
            evidence_refs=("utilization:zero",),
        ),
    )
    return DeterministicPolicyAdjudicator().evaluate(casefile, compilation.ir)
