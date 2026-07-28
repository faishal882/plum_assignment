from uuid import UUID

import pytest

from claims_backend.application.casefiles import (
    CasefileBuildRequest,
    EvidenceInsufficientForCasefileError,
    build_casefile,
)
from claims_backend.domain.reconciliation import (
    EvidenceCandidateSource,
    EvidenceSourceType,
    ProvenancedEvidenceCandidate,
    reconcile_evidence,
)

_CLAIM_ID = UUID("00000000-0000-0000-0000-000000000404")
_MEMBER_VERSION_ID = UUID("00000000-0000-0000-0000-000000000401")
_POLICY_VERSION_ID = UUID("00000000-0000-0000-0000-000000000402")
_MATERIAL_PATHS = (
    "billing.total",
    "claim.claimed_amount",
    "clinical.condition",
    "member.join_date",
    "patient.name",
    "treatment.date",
)


def test_casefile_freezes_reconciled_evidence_and_pinned_snapshots() -> None:
    reconciliation = reconcile_evidence(
        (
            _candidate("billing.total", "1500.00", "1500.00", 1),
            _candidate("claim.claimed_amount", 150_000, 150_000, 2),
            _candidate("clinical.condition", "Viral Fever", "viral fever", 3),
            _candidate("member.join_date", "2024-04-01", "2024-04-01", 4),
            _candidate("patient.name", "Rajesh Kumar", "Rajesh Kumar", 5),
            _candidate("treatment.date", "2024-11-01", "2024-11-01", 6),
            _candidate("billing.line_items.consultation_fee", "1000", "1000", 7),
        ),
        material_fact_paths=_MATERIAL_PATHS,
    )
    request = CasefileBuildRequest(
        claim_id=_CLAIM_ID,
        claim_version=1,
        member_id="EMP001",
        member_version_id=_MEMBER_VERSION_ID,
        member_snapshot_sha256="a" * 64,
        policy_version_id=_POLICY_VERSION_ID,
        category="CONSULTATION",
        claimed_paise=150_000,
        currency="INR",
        eligibility_evidence_ref=f"member-version:{_MEMBER_VERSION_ID}",
        document_roles=("PRESCRIPTION", "HOSPITAL_BILL"),
        document_role_evidence_refs=("triage:F007", "triage:F008"),
        ytd_used_paise=500_000,
        utilization_evidence_ref="utilization:2024-11-01",
        reconciliation=reconciliation,
    )

    first = build_casefile(request)
    repeated = build_casefile(request)

    assert first.schema_version == 3
    assert first.canonical_hash() == repeated.canonical_hash()
    assert first.member_snapshot_sha256 == "a" * 64
    assert first.evidence == reconciliation
    assert first.claimed_amount.value == 150_000
    assert first.billed_paise.value == 150_000
    assert first.treatment_date.value == "2024-11-01"
    assert first.member_join_date.value == "2024-04-01"
    assert first.patient_identity.value == "rajesh kumar"
    assert first.clinical_condition.value == "viral fever"
    assert first.line_items.value == ["billing.line_items.consultation_fee=100000"]
    assert first.line_item_facts[0].concept == "consultation_fee"
    assert first.line_item_facts[0].amount_paise == 100_000
    assert first.line_item_facts[0].evidence_refs == (f"{7:064x}",)


def test_casefile_cannot_be_built_from_insufficient_evidence() -> None:
    reconciliation = reconcile_evidence((), material_fact_paths=_MATERIAL_PATHS)
    request = CasefileBuildRequest(
        claim_id=_CLAIM_ID,
        claim_version=1,
        member_id="EMP001",
        member_version_id=_MEMBER_VERSION_ID,
        member_snapshot_sha256="a" * 64,
        policy_version_id=_POLICY_VERSION_ID,
        category="CONSULTATION",
        claimed_paise=150_000,
        currency="INR",
        eligibility_evidence_ref=f"member-version:{_MEMBER_VERSION_ID}",
        document_roles=("PRESCRIPTION", "HOSPITAL_BILL"),
        document_role_evidence_refs=("triage:F007", "triage:F008"),
        ytd_used_paise=500_000,
        utilization_evidence_ref="utilization:2024-11-01",
        reconciliation=reconciliation,
    )

    with pytest.raises(EvidenceInsufficientForCasefileError) as captured:
        build_casefile(request)

    assert captured.value.sufficiency == reconciliation.sufficiency


def _candidate(
    fact_path: str,
    value: str | int,
    normalized_value: str | int,
    index: int,
) -> ProvenancedEvidenceCandidate:
    return ProvenancedEvidenceCandidate(
        candidate_id=f"{index:064x}",
        fact_path=fact_path,
        value=value,
        normalized_value=normalized_value,
        producer="RECORDED",
        producer_version="recorded-v1",
        schema_version="evidence-v1",
        confidence=1,
        sources=(
            EvidenceCandidateSource(
                source_type=EvidenceSourceType.CLAIM_SNAPSHOT,
                source_ref=f"snapshot:{index}",
                source_sha256=f"{index + 100:064x}",
            ),
        ),
    )
