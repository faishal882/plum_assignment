import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claims_backend.domain.evidence import NormalizedRegion


class IdentityState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class IdentityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    producer: str = Field(min_length=1, max_length=64)
    producer_version: str = Field(min_length=1, max_length=64)
    client_document_id: str = Field(min_length=1, max_length=128)
    document_version_id: UUID
    page: int = Field(ge=1)
    region: NormalizedRegion
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence: float = Field(ge=0, le=1)
    value: str = Field(min_length=1, max_length=128)


class ReconciledIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: IdentityState
    member_name: str = Field(min_length=1, max_length=128)
    candidates: tuple[IdentityCandidate, ...]


class ReconciledFactState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class EvidenceSourceType(StrEnum):
    DOCUMENT = "DOCUMENT"
    CLAIM_SNAPSHOT = "CLAIM_SNAPSHOT"
    MEMBER_SNAPSHOT = "MEMBER_SNAPSHOT"
    UTILIZATION_SNAPSHOT = "UTILIZATION_SNAPSHOT"


type EvidenceScalar = str | int | float | bool | None


class EvidenceCandidateSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: EvidenceSourceType
    source_ref: str = Field(min_length=1, max_length=255)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    document_version_id: UUID | None = None
    page: int | None = Field(default=None, ge=1)
    region: NormalizedRegion | None = None

    @model_validator(mode="after")
    def document_provenance_is_complete(self) -> "EvidenceCandidateSource":
        document_fields = (
            self.observation_id,
            self.document_version_id,
            self.page,
            self.region,
        )
        if self.source_type is EvidenceSourceType.DOCUMENT:
            if any(value is None for value in document_fields):
                raise ValueError("Document evidence requires observation, page, and region.")
        elif any(value is not None for value in document_fields):
            raise ValueError("Snapshot evidence cannot claim document provenance.")
        return self


class ProvenancedEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_path: str = Field(min_length=1, max_length=128)
    value: EvidenceScalar
    normalized_value: EvidenceScalar
    producer: str = Field(min_length=1, max_length=64)
    producer_version: str = Field(min_length=1, max_length=128)
    schema_version: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)
    sources: tuple[EvidenceCandidateSource, ...] = Field(min_length=1)


class ReconciledFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_path: str
    state: ReconciledFactState
    value: EvidenceScalar
    candidate_ids: tuple[str, ...]


class EvidenceSufficiency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sufficient: bool
    unresolved_material_facts: tuple[str, ...]
    corrective_actions: tuple["EvidenceCorrectiveAction", ...]


class EvidenceCorrectiveAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_path: str
    code: str
    requested_action: str


class EvidenceReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: tuple[ProvenancedEvidenceCandidate, ...]
    facts: tuple[ReconciledFact, ...]
    sufficiency: EvidenceSufficiency


def reconcile_evidence(
    candidates: tuple[ProvenancedEvidenceCandidate, ...],
    *,
    material_fact_paths: tuple[str, ...],
) -> EvidenceReconciliation:
    ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    grouped: dict[str, list[ProvenancedEvidenceCandidate]] = defaultdict(list)
    for candidate in ordered:
        grouped[candidate.fact_path].append(candidate)
    all_paths = sorted(set(grouped) | set(material_fact_paths))
    facts = tuple(_reconcile_fact(path, tuple(grouped[path])) for path in all_paths)
    unresolved = tuple(
        fact.fact_path
        for fact in facts
        if fact.fact_path in material_fact_paths and fact.state is not ReconciledFactState.KNOWN
    )
    facts_by_path = {fact.fact_path: fact for fact in facts}
    return EvidenceReconciliation(
        candidates=ordered,
        facts=facts,
        sufficiency=EvidenceSufficiency(
            sufficient=not unresolved,
            unresolved_material_facts=unresolved,
            corrective_actions=tuple(
                _corrective_action(facts_by_path[path]) for path in unresolved
            ),
        ),
    )


def _reconcile_fact(
    fact_path: str,
    candidates: tuple[ProvenancedEvidenceCandidate, ...],
) -> ReconciledFact:
    if not candidates:
        return ReconciledFact(
            fact_path=fact_path,
            state=ReconciledFactState.UNKNOWN,
            value=None,
            candidate_ids=(),
        )
    canonical_values = {
        _canonical_fact_value(fact_path, candidate.normalized_value) for candidate in candidates
    }
    state = (
        ReconciledFactState.KNOWN if len(canonical_values) == 1 else ReconciledFactState.CONFLICT
    )
    return ReconciledFact(
        fact_path=fact_path,
        state=state,
        value=next(iter(canonical_values)) if state is ReconciledFactState.KNOWN else None,
        candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
    )


def _canonical_fact_value(fact_path: str, value: EvidenceScalar) -> EvidenceScalar:
    if fact_path == "claim.claimed_amount":
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return value
        cleaned = str(value).replace("INR", "").replace("₹", "").replace(",", "").strip()
        try:
            return int(Decimal(cleaned) * 100)
        except InvalidOperation:
            return cleaned.casefold()
    if fact_path == "billing.total" or fact_path.startswith("billing.line_items."):
        if isinstance(value, bool) or value is None:
            return value
        cleaned = str(value).replace("INR", "").replace("₹", "").replace(",", "").strip()
        try:
            return int(Decimal(cleaned) * 100)
        except InvalidOperation:
            return cleaned.casefold()
    if fact_path == "patient.name":
        return None if value is None else _normalize(str(value))
    if fact_path == "treatment.date":
        return None if value is None else str(value).strip()
    if fact_path.startswith("clinical."):
        normalized = "" if value is None else _normalize(str(value))
        if normalized in {"t2dm", "type 2 diabetes", "type 2 diabetes mellitus"}:
            return "diabetes"
        return normalized
    return value


def _corrective_action(fact: ReconciledFact) -> EvidenceCorrectiveAction:
    state = "CONFLICTING" if fact.state is ReconciledFactState.CONFLICT else "MISSING"
    if fact.fact_path.startswith("billing."):
        subject = "BILL_TOTAL" if fact.fact_path == "billing.total" else "BILL_LINE_ITEM"
        requested_action = "CORRECT_DOCUMENT" if state == "CONFLICTING" else "UPLOAD_DOCUMENT"
    elif fact.fact_path.startswith("clinical."):
        subject = "CLINICAL_EVIDENCE"
        requested_action = "CORRECT_DOCUMENT" if state == "CONFLICTING" else "UPLOAD_DOCUMENT"
    elif fact.fact_path == "patient.name":
        subject = "PATIENT_IDENTITY"
        requested_action = "CORRECT_DOCUMENT"
    elif fact.fact_path == "treatment.date":
        subject = "TREATMENT_DATE"
        requested_action = "CORRECT_DOCUMENT"
    else:
        subject = "MATERIAL_FACT"
        requested_action = "REVIEW"
    return EvidenceCorrectiveAction(
        fact_path=fact.fact_path,
        code=f"{state}_{subject}",
        requested_action=requested_action,
    )


def reconcile_patient_identity(
    member_name: str,
    candidates: tuple[IdentityCandidate, ...],
) -> ReconciledIdentity:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.client_document_id,
                str(item.document_version_id),
                item.page,
                item.source_text_sha256,
            ),
        )
    )
    if not ordered:
        state = IdentityState.UNKNOWN
    else:
        values = {_normalize(item.value) for item in ordered}
        state = (
            IdentityState.KNOWN if values == {_normalize(member_name)} else IdentityState.CONFLICT
        )
    return ReconciledIdentity(
        state=state,
        member_name=member_name,
        candidates=ordered,
    )


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()
