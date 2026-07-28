from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claims_backend.domain.adjudication import (
    AdjudicationRecommendation,
    ClaimCasefile,
    EvidenceFact,
    FactState,
    PreAuthorizationEvidence,
    RuleStatus,
)
from claims_backend.domain.evidence import NormalizedRegion
from claims_backend.domain.reconciliation import (
    EvidenceCandidateSource,
    EvidenceSourceType,
    ProvenancedEvidenceCandidate,
    reconcile_evidence,
)
from claims_backend.policy.adjudicator import (
    DeterministicPolicyAdjudicator,
    UnsafeCasefileError,
)
from claims_backend.policy.compiler import PolicyCompiler
from claims_backend.policy.explanation import render_member_explanation

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


def test_tc012_rejects_grounded_obesity_exclusion_before_amount_limits() -> None:
    proposal = _evaluate_clinical_case(
        condition="obesity",
        treatment="bariatric_treatment",
        amount_paise=800_000,
    )

    assert proposal.recommendation is AdjudicationRecommendation.REJECTED
    assert proposal.approved_paise == 0
    exclusion = proposal.rule_results[-1]
    assert exclusion.reason_code == "EXCLUDED_CONDITION"
    assert exclusion.policy_path == "/exclusions/conditions/5"
    assert exclusion.evidence_refs == ("c" * 64,)
    assert exclusion.inputs["matched_concept"] == "obesity"


def test_ungrounded_clinical_label_cannot_trigger_exclusion() -> None:
    with pytest.raises(UnsafeCasefileError, match="grounded"):
        _evaluate_clinical_case(
            condition="obesity",
            treatment="bariatric_treatment",
            amount_paise=800_000,
            source_type=EvidenceSourceType.CLAIM_SNAPSHOT,
        )


def test_neighboring_covered_condition_does_not_match_exclusion() -> None:
    proposal = _evaluate_clinical_case(
        condition="viral fever",
        treatment="nutrition counselling",
        amount_paise=300_000,
    )

    assert proposal.recommendation is AdjudicationRecommendation.APPROVED
    assert proposal.approved_paise == 270_000
    assert all(result.reason_code != "EXCLUDED_CONDITION" for result in proposal.rule_results)


def test_tc007_rejects_mri_above_threshold_without_pre_authorization() -> None:
    proposal = _evaluate_pre_authorization_case(
        treatment="mri",
        amount_paise=1_500_000,
    )

    assert proposal.recommendation is AdjudicationRecommendation.REJECTED
    assert proposal.approved_paise == 0
    authorization = proposal.rule_results[-1]
    assert authorization.status is RuleStatus.FAIL
    assert authorization.reason_code == "PRE_AUTH_MISSING"
    assert authorization.policy_path == "/clarifications/pre_authorization/MRI"
    assert authorization.inputs == {
        "treatment": "MRI",
        "eligible_paise": 1_500_000,
        "mode": "ABOVE_THRESHOLD",
        "threshold_paise": 1_000_000,
        "authorization_present": False,
    }
    explanation = render_member_explanation(proposal)
    assert "₹15,000.00" in explanation.summary
    assert "₹10,000.00" in explanation.summary
    assert "pre-authorization" in explanation.summary
    assert "resubmit" in explanation.summary


def test_valid_matching_pre_authorization_satisfies_mri_requirement() -> None:
    proposal = _evaluate_pre_authorization_case(
        treatment="mri",
        amount_paise=1_500_000,
        pre_authorized=True,
    )

    assert proposal.recommendation is AdjudicationRecommendation.APPROVED
    authorization = next(
        result for result in proposal.rule_results if result.reason_code == "PRE_AUTH_PRESENT"
    )
    assert authorization.status is RuleStatus.PASS
    assert authorization.evidence_refs[-1] == "authorization:amount"


def test_mri_threshold_and_pet_always_rules_are_exact() -> None:
    below = _evaluate_pre_authorization_case(
        treatment="mri",
        amount_paise=999_999,
    )
    equal = _evaluate_pre_authorization_case(
        treatment="mri",
        amount_paise=1_000_000,
    )
    above = _evaluate_pre_authorization_case(
        treatment="mri",
        amount_paise=1_000_001,
    )
    pet = _evaluate_pre_authorization_case(
        treatment="pet",
        amount_paise=500_000,
    )

    assert below.recommendation is AdjudicationRecommendation.APPROVED
    assert equal.recommendation is AdjudicationRecommendation.APPROVED
    assert above.rule_results[-1].reason_code == "PRE_AUTH_MISSING"
    assert pet.rule_results[-1].reason_code == "PRE_AUTH_MISSING"


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


def _evaluate_pre_authorization_case(
    *,
    treatment: str,
    amount_paise: int,
    pre_authorized: bool = False,
):
    compilation = PolicyCompiler().compile(POLICY_BYTES, OVERLAY_BYTES)
    assert compilation.ir is not None
    diagnostic = compilation.ir.category_rules["DIAGNOSTIC"]
    policy = compilation.ir.model_copy(
        update={
            "category_rules": {
                **compilation.ir.category_rules,
                "DIAGNOSTIC": diagnostic.model_copy(
                    update={"limit_paise": 2_000_000}
                ),
            }
        }
    )
    casefile = ClaimCasefile(
        schema_version=4,
        claim_id=UUID("00000000-0000-0000-0000-000000000707"),
        claim_version=1,
        member_id="EMP007",
        member_version_id=UUID("00000000-0000-0000-0000-000000000701"),
        member_snapshot_sha256="7" * 64,
        policy_version_id=UUID("00000000-0000-0000-0000-000000000702"),
        category="DIAGNOSTIC",
        claimed_paise=amount_paise,
        currency="INR",
        eligibility=EvidenceFact(
            state=FactState.KNOWN,
            value=True,
            evidence_refs=("member:active",),
        ),
        document_roles=EvidenceFact(
            state=FactState.KNOWN,
            value=[
                "PRESCRIPTION",
                "LAB_REPORT",
                "HOSPITAL_BILL",
                *(["PRE_AUTHORIZATION"] if pre_authorized else []),
            ],
            evidence_refs=("document:prescription", "document:report", "document:bill"),
        ),
        billed_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=amount_paise,
            evidence_refs=("document:bill-total",),
        ),
        claimed_amount=EvidenceFact(
            state=FactState.KNOWN,
            value=amount_paise,
            evidence_refs=("claim:amount",),
        ),
        treatment_date=EvidenceFact(
            state=FactState.KNOWN,
            value="2024-11-02",
            evidence_refs=("claim:treatment-date",),
        ),
        member_join_date=EvidenceFact(
            state=FactState.KNOWN,
            value="2024-04-01",
            evidence_refs=("member:join-date",),
        ),
        patient_identity=EvidenceFact(
            state=FactState.KNOWN,
            value="sanjay reddy",
            evidence_refs=("member:name",),
        ),
        clinical_condition=EvidenceFact(
            state=FactState.KNOWN,
            value="lumbar disc herniation",
            evidence_refs=("document:diagnosis",),
        ),
        clinical_treatment=EvidenceFact(
            state=FactState.KNOWN,
            value=treatment,
            evidence_refs=("document:test",),
        ),
        pre_authorization=(
            PreAuthorizationEvidence(
                patient_name=EvidenceFact(
                    state=FactState.KNOWN,
                    value="sanjay reddy",
                    evidence_refs=("authorization:patient",),
                ),
                treatment=EvidenceFact(
                    state=FactState.KNOWN,
                    value=treatment,
                    evidence_refs=("authorization:treatment",),
                ),
                valid_from=EvidenceFact(
                    state=FactState.KNOWN,
                    value="2024-10-01",
                    evidence_refs=("authorization:valid-from",),
                ),
                valid_to=EvidenceFact(
                    state=FactState.KNOWN,
                    value="2024-12-31",
                    evidence_refs=("authorization:valid-to",),
                ),
                reference=EvidenceFact(
                    state=FactState.KNOWN,
                    value="PA-007",
                    evidence_refs=("authorization:reference",),
                ),
                applicable_paise=EvidenceFact(
                    state=FactState.KNOWN,
                    value=amount_paise,
                    evidence_refs=("authorization:amount",),
                ),
            )
            if pre_authorized
            else None
        ),
        ytd_used_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=0,
            evidence_refs=("utilization:zero",),
        ),
    )
    return DeterministicPolicyAdjudicator().evaluate(casefile, policy)


def _evaluate_clinical_case(
    *,
    condition: str,
    treatment: str,
    amount_paise: int,
    source_type: EvidenceSourceType = EvidenceSourceType.DOCUMENT,
):
    compilation = PolicyCompiler().compile(POLICY_BYTES, OVERLAY_BYTES)
    assert compilation.ir is not None
    condition_candidate = _clinical_candidate(
        "c" * 64,
        "clinical.condition",
        condition,
        source_type,
    )
    treatment_candidate = _clinical_candidate(
        "d" * 64,
        "clinical.treatment",
        treatment,
        source_type,
    )
    evidence = reconcile_evidence(
        (condition_candidate, treatment_candidate),
        material_fact_paths=("clinical.condition",),
    )
    casefile = ClaimCasefile(
        schema_version=4,
        claim_id=UUID("00000000-0000-0000-0000-000000001212"),
        claim_version=1,
        member_id="EMP009",
        member_version_id=UUID("00000000-0000-0000-0000-000000001209"),
        member_snapshot_sha256="9" * 64,
        policy_version_id=UUID("00000000-0000-0000-0000-000000001202"),
        category="CONSULTATION",
        claimed_paise=amount_paise,
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
            value=amount_paise,
            evidence_refs=("document:bill-total",),
        ),
        claimed_amount=EvidenceFact(
            state=FactState.KNOWN,
            value=amount_paise,
            evidence_refs=("claim:amount",),
        ),
        treatment_date=EvidenceFact(
            state=FactState.KNOWN,
            value="2024-10-18",
            evidence_refs=("claim:treatment-date",),
        ),
        member_join_date=EvidenceFact(
            state=FactState.KNOWN,
            value="2024-04-01",
            evidence_refs=("member:join-date",),
        ),
        patient_identity=EvidenceFact(
            state=FactState.KNOWN,
            value="anita desai",
            evidence_refs=("member:name",),
        ),
        clinical_condition=EvidenceFact(
            state=FactState.KNOWN,
            value=condition,
            evidence_refs=(condition_candidate.candidate_id,),
        ),
        clinical_treatment=EvidenceFact(
            state=FactState.KNOWN,
            value=treatment,
            evidence_refs=(treatment_candidate.candidate_id,),
        ),
        ytd_used_paise=EvidenceFact(
            state=FactState.KNOWN,
            value=0,
            evidence_refs=("utilization:zero",),
        ),
        evidence=evidence,
    )
    return DeterministicPolicyAdjudicator().evaluate(casefile, compilation.ir)


def _clinical_candidate(
    candidate_id: str,
    fact_path: str,
    value: str,
    source_type: EvidenceSourceType,
) -> ProvenancedEvidenceCandidate:
    source = (
        EvidenceCandidateSource(
            source_type=EvidenceSourceType.DOCUMENT,
            source_ref=f"ocr:{candidate_id}",
            source_sha256="e" * 64,
            observation_id="e" * 64,
            document_version_id=UUID("00000000-0000-0000-0000-000000001223"),
            page=1,
            region=NormalizedRegion(x=0.1, y=0.1, width=0.8, height=0.1),
        )
        if source_type is EvidenceSourceType.DOCUMENT
        else EvidenceCandidateSource(
            source_type=source_type,
            source_ref="untrusted:model-label",
            source_sha256="e" * 64,
        )
    )
    return ProvenancedEvidenceCandidate(
        candidate_id=candidate_id,
        fact_path=fact_path,
        value=value,
        normalized_value=value,
        producer="BEDROCK",
        producer_version="qwen-live",
        schema_version="complex-extraction-v1",
        confidence=0.99,
        sources=(source,),
    )
