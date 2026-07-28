import json

from claims_backend.domain.extraction import ModelRoute
from claims_backend.infrastructure.fixtures.recorded_intelligence import (
    RecordedDocumentModelTransport,
)
from claims_backend.model.routing import ModelRouter


def test_recorded_transport_classifies_hash_selected_document_observations() -> None:
    transport = RecordedDocumentModelTransport()
    config = ModelRouter.default(region="local", model_id="recorded").resolve(
        ModelRoute.FAST_TRIAGE
    )
    response = transport.invoke(
        config,
        object,  # type: ignore[arg-type]
        [
            ("system", "unused"),
            (
                "human",
                json.dumps(
                    {
                        "documents": [
                            {
                                "client_document_id": "bill",
                                "observations": [{"text": "HOSPITAL_BILL"}],
                            }
                        ]
                    }
                ),
            ),
        ],
    )
    assert response.raw_output["documents"] == [
        {
            "client_document_id": "bill",
            "role": "HOSPITAL_BILL",
            "readability": {
                "status": "READABLE",
                "preview": response.raw_output["documents"][0]["readability"]["preview"],
            },
            "identity_observations": [],
        }
    ]


def test_recorded_transport_extracts_grounded_candidates() -> None:
    transport = RecordedDocumentModelTransport()
    config = ModelRouter.default(region="local", model_id="recorded").resolve(
        ModelRoute.COMPLEX_EXTRACTION
    )
    response = transport.invoke(
        config,
        object,  # type: ignore[arg-type]
        [
            ("system", "unused"),
            (
                "human",
                json.dumps(
                    {"ocr_observations": [{"observation_id": "a" * 64, "text": "HOSPITAL_BILL"}]}
                ),
            ),
        ],
    )
    candidates = response.raw_output["candidates"]
    assert any(item["fact_path"] == "billing.total" for item in candidates)
    assert all(item["evidence_refs"] == ["a" * 64] for item in candidates)
