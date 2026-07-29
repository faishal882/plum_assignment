import json
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.application.intelligence import (
    OcrApplication,
    PageArtifactApplication,
    PageArtifactRepository,
    RenderedPage,
    SourceDocument,
)
from claims_backend.config import Settings
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    TextractProfile,
)
from claims_backend.infrastructure.fixtures.recorded_model import (
    RecordedStructuredModelTransport,
)
from claims_backend.infrastructure.page_artifacts import (
    LocalPageArtifactReader,
    LocalPageArtifactStore,
)
from claims_backend.infrastructure.page_renderer import LocalPageRenderer
from claims_backend.infrastructure.postgres.models import (
    DocumentRow,
    DocumentVersionRow,
    EvidenceCandidateRow,
    ModelExtractionRow,
)
from claims_backend.infrastructure.postgres.ocr import PostgresOcrRepository
from claims_backend.infrastructure.postgres.page_artifacts import (
    PostgresPageArtifactRepository,
)
from claims_backend.infrastructure.postgres.structured_model import (
    PostgresStructuredModelRepository,
)
from claims_backend.model.application import StructuredModelApplication
from claims_backend.model.routing import ModelRouter


class RecordedObservationOcr:
    provider_name = "RECORDED_TEXTRACT"
    provider_version = "recorded-provenance-v1"

    def __init__(self, observation: OcrObservation) -> None:
        self._observation = observation

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        del page, role
        return OcrPageResult(
            profile=TextractProfile.TEXT,
            provider_request_id="recorded-provenance-request",
            retry_attempts=0,
            observations=(self._observation,),
        )


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
        document_version, document = (
            await session.execute(
                select(DocumentVersionRow, DocumentRow).join(
                    DocumentRow,
                    DocumentRow.id == DocumentVersionRow.document_id,
                )
            )
        ).one()
    document_version_id = document_version.id

    observation = _observation(document_version_id)
    page_repository: PageArtifactRepository = PostgresPageArtifactRepository(
        app.state.session_factory
    )
    artifacts = await PageArtifactApplication(
        LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024),
        LocalPageArtifactStore(tmp_path),
        page_repository,
    ).process(
        SourceDocument(
            document_id=document.id,
            document_version_id=document_version.id,
            relative_path=document_version.relative_path,
            media_type=document_version.media_type,
            sha256=document_version.sha256,
            page_count=document_version.page_count,
        )
    )
    await OcrApplication(
        LocalPageArtifactReader(tmp_path),
        RecordedObservationOcr(observation),
        PostgresOcrRepository(app.state.session_factory),
    ).process(artifacts, DocumentRole.UNKNOWN)
    recorded = RecordedStructuredModelTransport(
        {
            ModelRoute.FAST_TRIAGE: {
                "schema_version": 4,
                "documents": [
                    {
                        "client_document_id": "F-MODEL",
                        "role": "HOSPITAL_BILL",
                        "role_evidence_refs": [observation.observation_id],
                        "readability": "READABLE",
                        "readability_evidence_refs": [observation.observation_id],
                        "identity_observations": [],
                    }
                ],
            },
            ModelRoute.COMPLEX_EXTRACTION: {
                "schema_version": "complex-extraction-v1",
                "candidates": [
                    {
                        "fact_path": "clinical.diagnosis",
                        "value": "Viral Fever",
                        "normalized_value": "Viral Fever",
                        "evidence_refs": [observation.observation_id],
                        "confidence": 0.98,
                    }
                ],
            },
        }
    )
    repository = PostgresStructuredModelRepository(app.state.session_factory)
    model = StructuredModelApplication(
        ModelRouter.default(
            region="us-west-2",
            model_id="qwen.qwen3-235b-a22b-2507-v1:0",
        ),
        recorded,
        repository,
    )

    triage = await model.fast_triage([("human", "Recorded synthetic preview F-MODEL.")])
    first = await model.extract_complex(document_version_id, (observation,))
    replay = await model.extract_complex(document_version_id, (observation,))
    provenanced = await repository.list_provenanced_candidates(document_version_id)

    assert triage.output.documents[0].role.value == "HOSPITAL_BILL"
    assert first == replay
    assert first.candidates[0].fact_path == "clinical.condition"
    assert first.candidates[0].source_fact_path == "clinical.diagnosis"
    assert first.candidates[0].alias_registry_version == "fact-path-aliases-v1"
    assert first.candidates[0].evidence_refs == (observation.observation_id,)
    assert recorded.calls == [
        ModelRoute.FAST_TRIAGE,
        ModelRoute.COMPLEX_EXTRACTION,
    ]
    assert len(provenanced) == 1
    assert provenanced[0].value == "Viral Fever"
    assert provenanced[0].source_fact_path == "clinical.diagnosis"
    assert provenanced[0].alias_registry_version == "fact-path-aliases-v1"
    assert provenanced[0].producer == "BEDROCK"
    assert provenanced[0].producer_version.startswith("qwen.qwen3-235b-a22b-2507-v1:0")
    assert provenanced[0].schema_version == "complex-extraction-v1"
    assert provenanced[0].sources[0].observation_id == observation.observation_id
    assert provenanced[0].sources[0].document_version_id == document_version_id
    assert provenanced[0].sources[0].page == 1
    assert provenanced[0].sources[0].region == observation.region
    assert provenanced[0].sources[0].source_sha256 == sha256(observation.text.encode()).hexdigest()
    async with app.state.session_factory() as session:
        extraction_count = await session.scalar(
            select(func.count()).select_from(ModelExtractionRow)
        )
        candidate_count = await session.scalar(
            select(func.count()).select_from(EvidenceCandidateRow)
        )
        candidate = await session.scalar(select(EvidenceCandidateRow))
    assert extraction_count == 1
    assert candidate_count == 1
    assert candidate is not None
    assert candidate.source_fact_path == "clinical.diagnosis"
    assert candidate.alias_registry_version == "fact-path-aliases-v1"
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
