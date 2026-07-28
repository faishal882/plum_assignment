import json
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.domain.evidence import NormalizedRegion
from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.ocr import OcrObservation, OcrObservationKind
from claims_backend.infrastructure.fixtures.recorded_model import (
    RecordedStructuredModelTransport,
)
from claims_backend.infrastructure.postgres.models import (
    DocumentVersionRow,
    EvidenceCandidateRow,
    ModelExtractionRow,
)
from claims_backend.infrastructure.postgres.structured_model import (
    PostgresStructuredModelRepository,
)
from claims_backend.model.application import StructuredModelApplication
from claims_backend.model.routing import ModelRouter


@pytest.mark.asyncio
async def test_recorded_routes_validate_and_persist_without_network_calls(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "recorded-model",
            },
            data={"metadata": json.dumps(_metadata())},
            files={"files": ("synthetic.jpg", _image(), "image/jpeg")},
        )
    assert submitted.status_code == 202
    async with app.state.session_factory() as session:
        document_version_id = (await session.scalars(select(DocumentVersionRow.id))).one()

    observation = _observation(document_version_id)
    recorded = RecordedStructuredModelTransport(
        {
            ModelRoute.FAST_TRIAGE: {
                "schema_version": 2,
                "documents": [
                    {
                        "client_document_id": "F-MODEL",
                        "role": "HOSPITAL_BILL",
                        "readability": {
                            "status": "READABLE",
                            "preview": {
                                "page": 1,
                                "sha256": "a" * 64,
                                "transform_version": "recorded-preview-v1",
                            },
                        },
                        "identity_observations": [],
                    }
                ],
            },
            ModelRoute.COMPLEX_EXTRACTION: {
                "schema_version": "complex-extraction-v1",
                "candidates": [
                    {
                        "fact_path": "billing.total",
                        "value": "800.00",
                        "normalized_value": "800.00",
                        "evidence_refs": [observation.observation_id],
                        "confidence": 0.98,
                    }
                ],
            },
        }
    )
    model = StructuredModelApplication(
        ModelRouter.default(
            region="us-west-2",
            model_id="qwen.qwen3-235b-a22b-2507-v1:0",
        ),
        recorded,
        PostgresStructuredModelRepository(app.state.session_factory),
    )

    triage = await model.fast_triage([("human", "Recorded synthetic preview F-MODEL.")])
    first = await model.extract_complex(document_version_id, (observation,))
    replay = await model.extract_complex(document_version_id, (observation,))

    assert triage.output.documents[0].role.value == "HOSPITAL_BILL"
    assert first == replay
    assert first.candidates[0].fact_path == "billing.total"
    assert first.candidates[0].evidence_refs == (observation.observation_id,)
    assert recorded.calls == [
        ModelRoute.FAST_TRIAGE,
        ModelRoute.COMPLEX_EXTRACTION,
    ]
    async with app.state.session_factory() as session:
        extraction_count = await session.scalar(
            select(func.count()).select_from(ModelExtractionRow)
        )
        candidate_count = await session.scalar(
            select(func.count()).select_from(EvidenceCandidateRow)
        )
    assert extraction_count == 1
    assert candidate_count == 1
    await app.state.engine.dispose()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "800.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "F-MODEL"}],
    }


def _image() -> bytes:
    output = BytesIO()
    Image.new("RGB", (320, 180), "white").save(output, format="JPEG")
    return output.getvalue()


def _observation(document_version_id: UUID) -> OcrObservation:
    observation_id = sha256(f"{document_version_id}:line-1".encode()).hexdigest()
    return OcrObservation(
        observation_id=observation_id,
        document_version_id=document_version_id,
        page_number=1,
        kind=OcrObservationKind.LINE,
        text="Total 800.00",
        confidence=0.99,
        region=NormalizedRegion(x=0.1, y=0.1, width=0.4, height=0.1),
        source_id="line-1",
    )
