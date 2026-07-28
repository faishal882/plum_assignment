import pytest
from pydantic import ValidationError

from claims_backend.domain.evidence import DocumentRole, TriageModelOutput


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
        "schema_version": 1,
        "documents": [
            {
                "client_document_id": "F007",
                "role": "PRESCRIPTION",
                "readability": "READABLE",
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
            "schema_version": 1,
            "documents": [
                {
                    "client_document_id": "F099",
                    "role": "UNKNOWN",
                    "readability": "UNKNOWN",
                    "identity_observations": [],
                }
            ],
        }
    )

    assert output.documents[0].role is DocumentRole.UNKNOWN


def test_triage_identity_observations_are_bounded() -> None:
    observations = [
        {"kind": "PATIENT_NAME", "value": name} for name in ("First", "Second", "Third")
    ]

    with pytest.raises(ValidationError):
        TriageModelOutput.model_validate(
            {
                "schema_version": 1,
                "documents": [
                    {
                        "client_document_id": "F001",
                        "role": "PRESCRIPTION",
                        "readability": "READABLE",
                        "identity_observations": observations,
                    }
                ],
            }
        )
