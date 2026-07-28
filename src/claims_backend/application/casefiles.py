from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from claims_backend.domain.adjudication import (
    CasefileLineItem,
    ClaimCasefile,
    EvidenceFact,
    FactState,
    PreAuthorizationEvidence,
)
from claims_backend.domain.reconciliation import (
    EvidenceReconciliation,
    EvidenceSufficiency,
    ProvenancedEvidenceCandidate,
    ReconciledFact,
    ReconciledFactState,
)


class EvidenceInsufficientForCasefileError(ValueError):
    def __init__(self, sufficiency: EvidenceSufficiency) -> None:
        self.sufficiency = sufficiency
        super().__init__("Material evidence is unresolved; casefile cannot be frozen.")


class ProvenancedEvidenceRepository(Protocol):
    async def list_provenanced_candidates(
        self,
        document_version_id: UUID,
    ) -> tuple[ProvenancedEvidenceCandidate, ...]: ...


@dataclass(frozen=True, slots=True)
class CasefileBuildRequest:
    claim_id: UUID
    claim_version: int
    member_id: str
    member_version_id: UUID
    member_snapshot_sha256: str
    policy_version_id: UUID
    category: str
    claimed_paise: int
    currency: str
    eligibility_evidence_ref: str
    document_roles: tuple[str, ...]
    document_role_evidence_refs: tuple[str, ...]
    ytd_used_paise: int | None
    utilization_evidence_ref: str | None
    reconciliation: EvidenceReconciliation


def build_casefile(request: CasefileBuildRequest) -> ClaimCasefile:
    if not request.reconciliation.sufficiency.sufficient:
        raise EvidenceInsufficientForCasefileError(request.reconciliation.sufficiency)
    facts = {fact.fact_path: fact for fact in request.reconciliation.facts}
    line_item_facts = tuple(
        fact
        for fact in request.reconciliation.facts
        if fact.fact_path.startswith("billing.line_items.")
        and fact.state is ReconciledFactState.KNOWN
    )
    line_item_refs = tuple(
        candidate_id for fact in line_item_facts for candidate_id in fact.candidate_ids
    )
    return ClaimCasefile(
        schema_version=5,
        claim_id=request.claim_id,
        claim_version=request.claim_version,
        member_id=request.member_id,
        member_version_id=request.member_version_id,
        member_snapshot_sha256=request.member_snapshot_sha256,
        policy_version_id=request.policy_version_id,
        category=request.category,
        claimed_paise=request.claimed_paise,
        currency=request.currency,
        eligibility=EvidenceFact(
            state=FactState.KNOWN,
            value=True,
            evidence_refs=(request.eligibility_evidence_ref,),
        ),
        document_roles=EvidenceFact(
            state=FactState.KNOWN,
            value=list(request.document_roles),
            evidence_refs=request.document_role_evidence_refs,
        ),
        billed_paise=_evidence_fact(_required_fact(facts, "billing.total")),
        claimed_amount=_evidence_fact(_required_fact(facts, "claim.claimed_amount")),
        treatment_date=_evidence_fact(_required_fact(facts, "treatment.date")),
        member_join_date=_evidence_fact(_required_fact(facts, "member.join_date")),
        patient_identity=_evidence_fact(_required_fact(facts, "patient.name")),
        clinical_condition=_optional_evidence_fact(facts.get("clinical.condition")),
        clinical_treatment=_optional_evidence_fact(facts.get("clinical.treatment")),
        line_items=EvidenceFact(
            state=FactState.KNOWN if line_item_facts else FactState.UNKNOWN,
            value=[f"{fact.fact_path}={fact.value}" for fact in line_item_facts],
            evidence_refs=line_item_refs,
        ),
        line_item_facts=tuple(
            CasefileLineItem(
                fact_path=fact.fact_path,
                concept=fact.fact_path.removeprefix("billing.line_items."),
                amount_paise=_integer_fact_value(fact),
                evidence_refs=fact.candidate_ids,
            )
            for fact in line_item_facts
        ),
        pre_authorization=_pre_authorization(facts),
        ytd_used_paise=EvidenceFact(
            state=(FactState.KNOWN if request.ytd_used_paise is not None else FactState.UNKNOWN),
            value=request.ytd_used_paise,
            evidence_refs=(
                ()
                if request.utilization_evidence_ref is None
                else (request.utilization_evidence_ref,)
            ),
        ),
        evidence=request.reconciliation,
    )


def _required_fact(
    facts: dict[str, ReconciledFact],
    fact_path: str,
) -> ReconciledFact:
    fact = facts.get(fact_path)
    if fact is None or fact.state is not ReconciledFactState.KNOWN:
        raise ValueError(f"Required reconciled fact is unavailable: {fact_path}.")
    return fact


def _evidence_fact(fact: ReconciledFact) -> EvidenceFact:
    return EvidenceFact.model_validate(
        {
            "state": FactState.KNOWN,
            "value": fact.value,
            "evidence_refs": fact.candidate_ids,
        }
    )


def _optional_evidence_fact(fact: ReconciledFact | None) -> EvidenceFact | None:
    if fact is None or fact.state is not ReconciledFactState.KNOWN:
        return None
    return _evidence_fact(fact)


def _integer_fact_value(fact: ReconciledFact) -> int:
    if isinstance(fact.value, bool) or not isinstance(fact.value, int):
        raise ValueError(f"Reconciled monetary fact is not integer paise: {fact.fact_path}.")
    return fact.value


def _pre_authorization(
    facts: dict[str, ReconciledFact],
) -> PreAuthorizationEvidence | None:
    prefix = "document.pre_authorization."
    field_paths = {
        "patient_name": f"{prefix}patient_name",
        "treatment": f"{prefix}treatment",
        "valid_from": f"{prefix}valid_from",
        "valid_to": f"{prefix}valid_to",
        "reference": f"{prefix}reference",
        "applicable_paise": f"{prefix}applicable_amount",
    }
    if not any(path in facts for path in field_paths.values()):
        return None
    return PreAuthorizationEvidence(
        **{
            field: _evidence_fact(_required_fact(facts, path))
            for field, path in field_paths.items()
        }
    )
