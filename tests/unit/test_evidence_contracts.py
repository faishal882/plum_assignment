import pytest
from pydantic import ValidationError

from claims_backend.domain.evidence import DocumentRole, Readability, TriageModelOutput


def test_triage_model_contract_contains_only_semantics_and_opaque_references() -> None:
    output = TriageModelOutput.model_validate(_payload())

    document = output.documents[0]
    assert output.schema_version == 3
    assert document.role is DocumentRole.PRESCRIPTION
    assert document.readability is Readability.READABLE
    assert document.identity_observations[0].observation_id == "b" * 64


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("document", "preview_sha256", "c" * 64),
        ("document", "page", 1),
        ("document", "region", {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1}),
        ("identity", "source_text_sha256", "d" * 64),
        ("identity", "confidence", 0.98),
    ],
)
def test_triage_model_contract_rejects_backend_owned_provenance(
    target: str,
    field: str,
    value: object,
) -> None:
    payload = _payload()
    document = payload["documents"][0]
    destination = document if target == "document" else document["identity_observations"][0]
    destination[field] = value

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(payload)


@pytest.mark.parametrize(
    "forbidden",
    [
        {"decision": "APPROVED"},
        {"reason_code": "COVERED"},
        {"approved_amount": 1350},
    ],
)
def test_model_boundary_forbids_financial_authority_fields(
    forbidden: dict[str, object],
) -> None:
    payload = {**_payload(), **forbidden}

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(payload)


def test_unknown_document_role_remains_explicitly_unknown() -> None:
    payload = _payload()
    payload["documents"][0]["role"] = "UNKNOWN"
    payload["documents"][0]["readability"] = "UNKNOWN"

    output = TriageModelOutput.model_validate(payload)

    assert output.documents[0].role is DocumentRole.UNKNOWN


def test_triage_identity_observations_are_bounded() -> None:
    payload = _payload()
    payload["documents"][0]["identity_observations"] = [
        _identity("First", "b" * 64),
        _identity("Second", "c" * 64),
        _identity("Third", "d" * 64),
        _identity("Fourth", "e" * 64),
        _identity("Fifth", "f" * 64),
    ]

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(payload)


def _payload() -> dict[str, object]:
    return {
        "schema_version": 3,
        "documents": [
            {
                "client_document_id": "F005",
                "role": "PRESCRIPTION",
                "role_evidence_refs": ["a" * 64],
                "readability": "READABLE",
                "readability_evidence_refs": ["a" * 64],
                "identity_observations": [_identity("Rajesh Kumar", "b" * 64)],
            }
        ],
    }


def _identity(value: str, observation_id: str) -> dict[str, object]:
    return {
        "kind": "PATIENT_NAME",
        "value": value,
        "observation_id": observation_id,
    }
