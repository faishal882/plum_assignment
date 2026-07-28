from typing import Any
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

from claims_backend.domain.evidence import NormalizedRegion
from claims_backend.domain.reconciliation import (
    EvidenceCandidateSource,
    EvidenceSourceType,
    ProvenancedEvidenceCandidate,
    ReconciledFactState,
    reconcile_evidence,
)


def test_candidates_are_grouped_without_losing_original_provenance() -> None:
    first = _candidate(
        candidate_id="a" * 64,
        value="INR 1,500.00",
        normalized_value="1500.00",
        observation_id="1" * 64,
        page=1,
    )
    repeated = _candidate(
        candidate_id="b" * 64,
        value="1500",
        normalized_value="1500.00",
        observation_id="2" * 64,
        page=2,
    )

    result = reconcile_evidence(
        (repeated, first),
        material_fact_paths=("billing.total",),
    )

    assert result.sufficiency.sufficient
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert fact.fact_path == "billing.total"
    assert fact.state is ReconciledFactState.KNOWN
    assert fact.value == 150_000
    assert fact.candidate_ids == ("a" * 64, "b" * 64)
    assert [candidate.value for candidate in result.candidates] == [
        "INR 1,500.00",
        "1500",
    ]
    assert result.candidates[0].sources[0].page == 1
    assert result.candidates[0].sources[0].source_sha256 == "3" * 64


def test_unknown_and_conflicting_material_facts_return_specific_corrections() -> None:
    first = _candidate(
        candidate_id="a" * 64,
        value="1500.00",
        normalized_value="1500.00",
        observation_id="1" * 64,
        page=1,
    )
    conflicting = _candidate(
        candidate_id="b" * 64,
        value="1800.00",
        normalized_value="1800.00",
        observation_id="2" * 64,
        page=1,
    )

    result = reconcile_evidence(
        (first, conflicting),
        material_fact_paths=("billing.total", "clinical.condition"),
    )

    assert not result.sufficiency.sufficient
    assert result.sufficiency.unresolved_material_facts == (
        "billing.total",
        "clinical.condition",
    )
    assert [(fact.fact_path, fact.state) for fact in result.facts] == [
        ("billing.total", ReconciledFactState.CONFLICT),
        ("clinical.condition", ReconciledFactState.UNKNOWN),
    ]
    assert [
        (action.fact_path, action.code, action.requested_action)
        for action in result.sufficiency.corrective_actions
    ] == [
        ("billing.total", "CONFLICTING_BILL_TOTAL", "CORRECT_DOCUMENT"),
        ("clinical.condition", "MISSING_CLINICAL_EVIDENCE", "UPLOAD_DOCUMENT"),
    ]


def test_trusted_snapshot_and_document_sources_share_one_evidence_graph() -> None:
    member_candidate = ProvenancedEvidenceCandidate(
        candidate_id="c" * 64,
        fact_path="patient.name",
        value="Rajesh Kumar",
        normalized_value="Rajesh Kumar",
        producer="MEMBER_SNAPSHOT",
        producer_version="member-version-v1",
        schema_version="member-snapshot-v1",
        confidence=1,
        sources=(
            EvidenceCandidateSource(
                source_type=EvidenceSourceType.MEMBER_SNAPSHOT,
                source_ref="member-version:00000000-0000-0000-0000-000000000401",
                source_sha256="4" * 64,
            ),
        ),
    )
    document_candidate = ProvenancedEvidenceCandidate(
        candidate_id="d" * 64,
        fact_path="patient.name",
        value="RAJESH  KUMAR",
        normalized_value="RAJESH KUMAR",
        producer="BEDROCK",
        producer_version="qwen-v1",
        schema_version="complex-extraction-v1",
        confidence=0.95,
        sources=(
            EvidenceCandidateSource(
                source_type=EvidenceSourceType.DOCUMENT,
                source_ref="ocr:5" + "5" * 63,
                observation_id="5" * 64,
                document_version_id=UUID("00000000-0000-0000-0000-000000000111"),
                page=1,
                region=NormalizedRegion(x=0.1, y=0.2, width=0.3, height=0.1),
                source_sha256="6" * 64,
            ),
        ),
    )

    result = reconcile_evidence(
        (document_candidate, member_candidate),
        material_fact_paths=("patient.name",),
    )

    assert result.facts[0].state is ReconciledFactState.KNOWN
    assert result.facts[0].value == "rajesh kumar"
    assert result.sufficiency.sufficient


@given(
    data=st.data(),
    amounts=st.lists(
        st.integers(min_value=1, max_value=100_000),
        min_size=1,
        max_size=6,
        unique=True,
    ),
)
def test_reconciliation_is_stable_under_candidate_reordering(
    data: Any,
    amounts: list[int],
) -> None:
    candidates = tuple(
        _candidate(
            candidate_id=f"{index:064x}",
            value=str(amount),
            normalized_value=str(amount),
            observation_id=f"{index + 100:064x}",
            page=index + 1,
        )
        for index, amount in enumerate(amounts, start=1)
    )
    permuted = tuple(data.draw(st.permutations(candidates)))

    assert reconcile_evidence(
        candidates,
        material_fact_paths=("billing.total",),
    ) == reconcile_evidence(
        permuted,
        material_fact_paths=("billing.total",),
    )


def _candidate(
    *,
    candidate_id: str,
    value: str,
    normalized_value: str,
    observation_id: str,
    page: int,
) -> ProvenancedEvidenceCandidate:
    return ProvenancedEvidenceCandidate(
        candidate_id=candidate_id,
        fact_path="billing.total",
        value=value,
        normalized_value=normalized_value,
        producer="BEDROCK",
        producer_version="qwen.qwen3-235b-a22b-2507-v1:0",
        schema_version="complex-extraction-v1",
        confidence=0.98,
        sources=(
            EvidenceCandidateSource(
                source_type=EvidenceSourceType.DOCUMENT,
                source_ref=f"ocr:{observation_id}",
                observation_id=observation_id,
                document_version_id=UUID("00000000-0000-0000-0000-000000000111"),
                page=page,
                region=NormalizedRegion(x=0.1, y=0.2, width=0.3, height=0.1),
                source_sha256="3" * 64,
            ),
        ),
    )
