import pytest
from pydantic import ValidationError

from claims_backend.domain.evidence import DocumentRole, Readability, TriageModelOutput


def test_triage_observations_require_preview_and_source_provenance() -> None:
    output = TriageModelOutput.model_validate(
        {
            "schema_version": 2,
            "documents": [
                {
                    "client_document_id": "F005",
                    "role": "PRESCRIPTION",
                    "readability": {
                        "status": "READABLE",
                        "preview": {
                            "page": 1,
                            "sha256": "a" * 64,
                            "transform_version": "preview-v1",
                        },
                    },
                    "identity_observations": [
                        {
                            "kind": "PATIENT_NAME",
                            "value": "Rajesh Kumar",
                            "page": 1,
                            "region": {
                                "x": 0.1,
                                "y": 0.2,
                                "width": 0.3,
                                "height": 0.1,
                            },
                            "source_text_sha256": "b" * 64,
                            "confidence": 0.98,
                        }
                    ],
                }
            ],
        }
    )

    assert output.documents[0].readability.status is Readability.READABLE
    assert output.documents[0].readability.preview.page == 1
    assert output.documents[0].identity_observations[0].confidence == 0.98

    incomplete = output.model_dump(mode="json")
    del incomplete["documents"][0]["identity_observations"][0]["source_text_sha256"]
    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(incomplete)


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
    payload = {
        "schema_version": 2,
        "documents": [
            {
                "client_document_id": "F007",
                "role": "PRESCRIPTION",
                "readability": _readability("READABLE"),
                "identity_observations": [],
            }
        ],
        **forbidden,
    }

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(payload)


def test_unknown_document_role_remains_explicitly_unknown() -> None:
    output = TriageModelOutput.model_validate(
        {
            "schema_version": 2,
            "documents": [
                {
                    "client_document_id": "F099",
                    "role": "UNKNOWN",
                    "readability": _readability("UNKNOWN"),
                    "identity_observations": [],
                }
            ],
        }
    )

    assert output.documents[0].role is DocumentRole.UNKNOWN


def test_triage_identity_observations_are_bounded() -> None:
    observations = [_identity(name) for name in ("First", "Second", "Third")]

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(
            {
                "schema_version": 2,
                "documents": [
                    {
                        "client_document_id": "F001",
                        "role": "PRESCRIPTION",
                        "readability": _readability("READABLE"),
                        "identity_observations": observations,
                    }
                ],
            }
        )


def _readability(status: str) -> dict[str, object]:
    return {
        "status": status,
        "preview": {
            "page": 1,
            "sha256": "a" * 64,
            "transform_version": "preview-v1",
        },
    }


def _identity(value: str) -> dict[str, object]:
    return {
        "kind": "PATIENT_NAME",
        "value": value,
        "page": 1,
        "region": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1},
        "source_text_sha256": "b" * 64,
        "confidence": 0.9,
    }
