import pytest
from pydantic import ValidationError

from claims_backend.api.schemas import ClaimMetadataRequest


def test_claim_request_cannot_supply_member_history() -> None:
    with pytest.raises(ValidationError) as captured:
        ClaimMetadataRequest.model_validate(
            {
                "member_id": "EMP008",
                "policy_id": "PLUM_GHI_2024",
                "claim_category": "CONSULTATION",
                "treatment_date": "2024-10-30",
                "claimed_amount": "4800.00",
                "currency": "INR",
                "documents": [
                    {
                        "upload_index": 0,
                        "client_document_id": "F017",
                    }
                ],
                "claims_history": [
                    {
                        "claim_id": "UNTRUSTED",
                        "date": "2024-10-30",
                        "amount": 999999,
                    }
                ],
            }
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"
