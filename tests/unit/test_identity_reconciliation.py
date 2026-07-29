from uuid import UUID

from claims_backend.domain.evidence import NormalizedRegion
from claims_backend.domain.reconciliation import (
    IdentityCandidate,
    IdentityState,
    reconcile_patient_identity,
)


def test_conflicting_patient_names_survive_source_order_and_confidence() -> None:
    rajesh = _candidate(
        "F005",
        "Rajesh Kumar",
        confidence=0.72,
        document_version_id="00000000-0000-0000-0000-000000000005",
    )
    arjun = _candidate(
        "F006",
        "Arjun Mehta",
        confidence=0.99,
        document_version_id="00000000-0000-0000-0000-000000000006",
    )

    forward = reconcile_patient_identity("Rajesh Kumar", (rajesh, arjun))
    reversed_order = reconcile_patient_identity("Rajesh Kumar", (arjun, rajesh))

    assert forward.state is IdentityState.CONFLICT
    assert reversed_order == forward
    assert [(item.client_document_id, item.value) for item in forward.candidates] == [
        ("F005", "Rajesh Kumar"),
        ("F006", "Arjun Mehta"),
    ]


def test_identity_reconciliation_distinguishes_known_from_unknown() -> None:
    unknown = reconcile_patient_identity("Rajesh Kumar", ())
    known = reconcile_patient_identity(
        "Rajesh Kumar",
        (
            _candidate(
                "F005",
                "  RAJESH   KUMAR ",
                confidence=0.51,
                document_version_id="00000000-0000-0000-0000-000000000005",
            ),
        ),
    )

    assert unknown.state is IdentityState.UNKNOWN
    assert known.state is IdentityState.KNOWN


def test_identity_reconciliation_accepts_same_document_tokenized_full_name() -> None:
    first = _candidate(
        "F005",
        "Rajesh",
        confidence=0.99,
        document_version_id="00000000-0000-0000-0000-000000000005",
        x=0.20,
    )
    last = _candidate(
        "F005",
        "Kumar",
        confidence=0.99,
        document_version_id="00000000-0000-0000-0000-000000000005",
        x=0.30,
    )

    result = reconcile_patient_identity("Rajesh Kumar", (last, first))

    assert result.state is IdentityState.KNOWN


def _candidate(
    client_document_id: str,
    value: str,
    *,
    confidence: float,
    document_version_id: str,
    x: float = 0.1,
) -> IdentityCandidate:
    return IdentityCandidate(
        producer="fixture-fast-triage",
        producer_version="v1",
        client_document_id=client_document_id,
        document_version_id=UUID(document_version_id),
        page=1,
        region=NormalizedRegion(x=x, y=0.1, width=0.5, height=0.1),
        source_text_sha256="a" * 64,
        confidence=confidence,
        value=value,
    )
