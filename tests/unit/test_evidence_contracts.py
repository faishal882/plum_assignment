import pytest
from pydantic import ValidationError

from claims_backend.domain.evidence import TriageModelOutput


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
