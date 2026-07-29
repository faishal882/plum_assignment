"""Deterministic, versioned evidence-reference policy selection."""

from dataclasses import dataclass

from claims_backend.domain.evidence import (
    TriageEvidenceField,
    TriageEvidenceFieldNormalization,
    TriageEvidenceNormalizationCode,
)
from claims_backend.domain.extraction import (
    ModelGroundingValidationError,
    ModelOutputLimitExceeded,
)

TRIAGE_EVIDENCE_POLICY_LEGACY = "triage-evidence-policy-legacy-v0"
TRIAGE_EVIDENCE_POLICY_V1 = "triage-evidence-policy-v1"


class EvidenceReferencePolicyUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EvidenceReferencePolicy:
    version: str
    provider_reference_limit: int
    canonical_reference_limit: int


_POLICIES = {
    TRIAGE_EVIDENCE_POLICY_V1: EvidenceReferencePolicy(
        version=TRIAGE_EVIDENCE_POLICY_V1,
        provider_reference_limit=100,
        canonical_reference_limit=5,
    ),
}


def resolve_evidence_reference_policy(version: str) -> EvidenceReferencePolicy:
    try:
        return _POLICIES[version]
    except KeyError as error:
        raise EvidenceReferencePolicyUnavailableError(
            f"Unsupported triage evidence policy {version!r}."
        ) from error


def normalize_evidence_references(
    references: tuple[str, ...],
    *,
    field: TriageEvidenceField,
    available_observation_ids: frozenset[str],
    policy: EvidenceReferencePolicy,
) -> TriageEvidenceFieldNormalization:
    """Validate all references before stable canonical reduction."""

    if len(references) > policy.provider_reference_limit:
        raise ModelOutputLimitExceeded(
            "Triage provider output exceeds the evidence-reference safety ceiling."
        )
    unavailable = [
        reference for reference in references if reference not in available_observation_ids
    ]
    if unavailable:
        raise ModelGroundingValidationError(
            "Triage output references an unavailable OCR observation."
        )
    unique: list[str] = []
    duplicate_dropped: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if reference in seen:
            duplicate_dropped.append(reference)
        else:
            seen.add(reference)
            unique.append(reference)
    retained = unique[: policy.canonical_reference_limit]
    over_citation_dropped = unique[policy.canonical_reference_limit :]
    codes: list[TriageEvidenceNormalizationCode] = []
    if duplicate_dropped:
        codes.append(TriageEvidenceNormalizationCode.DEDUPLICATED)
    if over_citation_dropped:
        codes.append(TriageEvidenceNormalizationCode.TRUNCATED)
    return TriageEvidenceFieldNormalization(
        field=field,
        received_refs=tuple(references),
        unique_refs=tuple(unique),
        retained_refs=tuple(retained),
        duplicate_dropped_refs=tuple(duplicate_dropped),
        over_citation_dropped_refs=tuple(over_citation_dropped),
        codes=tuple(codes),
    )
