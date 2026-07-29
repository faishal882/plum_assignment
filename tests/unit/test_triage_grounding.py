from hashlib import sha256
from uuid import UUID

import pytest

from claims_backend.domain.evidence import (
    DocumentRole,
    NormalizedRegion,
    PreviewProvenance,
    Readability,
    TriageDocumentPrediction,
    TriageIdentitySelection,
    TriageModelOutput,
)
from claims_backend.domain.extraction import ModelGroundingValidationError
from claims_backend.domain.ocr import OcrObservation, OcrObservationKind
from claims_backend.model.triage import TriageDocumentContext, resolve_triage_output


def test_triage_predictions_are_hydrated_from_backend_owned_provenance() -> None:
    document_version_id = UUID("10000000-0000-0000-0000-000000000001")
    observation = OcrObservation(
        observation_id="a" * 64,
        document_version_id=document_version_id,
        page_number=2,
        kind=OcrObservationKind.LINE,
        text="Patient Name: Rajesh Kumar",
        confidence=0.93,
        region=NormalizedRegion(x=0.1, y=0.2, width=0.6, height=0.1),
        source_id="textract-line-1",
    )
    preview = PreviewProvenance(
        page=2,
        sha256="b" * 64,
        transform_version="pymupdf-v1",
    )
    output = TriageModelOutput(
        documents=(
            TriageDocumentPrediction(
                client_document_id="doc-123",
                role=DocumentRole.HOSPITAL_BILL,
                role_evidence_refs=(observation.observation_id,),
                readability=Readability.READABLE,
                readability_evidence_refs=(observation.observation_id,),
                identity_observations=(
                    TriageIdentitySelection(
                        value="Rajesh Kumar",
                        observation_id=observation.observation_id,
                    ),
                ),
            ),
        )
    )

    resolved = resolve_triage_output(
        output,
        (
            TriageDocumentContext(
                client_document_id="doc-123",
                document_version_id=document_version_id,
                observations=(observation,),
                previews_by_page={2: preview},
            ),
        ),
    )

    document = resolved.documents[0]
    identity = document.identity_observations[0]
    assert resolved.schema_version == 3
    assert document.role_evidence_refs == (observation.observation_id,)
    assert document.readability_evidence_refs == (observation.observation_id,)
    assert document.readability.preview == preview
    assert identity.value == "Rajesh Kumar"
    assert identity.observation_id == observation.observation_id
    assert identity.page == observation.page_number
    assert identity.region == observation.region
    assert identity.confidence == observation.confidence
    assert identity.source_text_sha256 == sha256(observation.text.encode()).hexdigest()


def test_triage_rejects_an_observation_reference_from_another_document() -> None:
    first = _observation("a" * 64, "10000000-0000-0000-0000-000000000001")
    second = _observation("b" * 64, "10000000-0000-0000-0000-000000000002")
    output = TriageModelOutput(
        documents=(
            TriageDocumentPrediction(
                client_document_id="doc-1",
                role=DocumentRole.PRESCRIPTION,
                role_evidence_refs=(second.observation_id,),
                readability=Readability.READABLE,
                readability_evidence_refs=(first.observation_id,),
                identity_observations=(),
            ),
        )
    )

    with pytest.raises(ModelGroundingValidationError):
        resolve_triage_output(
            output,
            (
                TriageDocumentContext(
                    client_document_id="doc-1",
                    document_version_id=first.document_version_id,
                    observations=(first,),
                    previews_by_page={
                        1: PreviewProvenance(
                            page=1,
                            sha256="c" * 64,
                            transform_version="pymupdf-v1",
                        )
                    },
                ),
            ),
        )


def test_empty_ocr_becomes_a_deterministic_unreadable_result() -> None:
    document_version_id = UUID("10000000-0000-0000-0000-000000000003")
    resolved = resolve_triage_output(
        None,
        (
            TriageDocumentContext(
                client_document_id="doc-empty",
                document_version_id=document_version_id,
                observations=(),
                previews_by_page={
                    1: PreviewProvenance(
                        page=1,
                        sha256="d" * 64,
                        transform_version="pymupdf-v1",
                    )
                },
            ),
        ),
    )

    document = resolved.documents[0]
    assert document.role is DocumentRole.UNKNOWN
    assert document.readability.status is Readability.UNREADABLE
    assert document.role_evidence_refs == ()
    assert document.readability_evidence_refs == ()
    assert document.identity_observations == ()


def test_triage_rejects_an_identity_value_not_present_in_referenced_text() -> None:
    observation = _observation("a" * 64, "10000000-0000-0000-0000-000000000004")
    output = TriageModelOutput(
        documents=(
            TriageDocumentPrediction(
                client_document_id="doc-identity",
                role=DocumentRole.PRESCRIPTION,
                role_evidence_refs=(observation.observation_id,),
                readability=Readability.READABLE,
                readability_evidence_refs=(observation.observation_id,),
                identity_observations=(
                    TriageIdentitySelection(
                        value="Invented Patient",
                        observation_id=observation.observation_id,
                    ),
                ),
            ),
        )
    )

    with pytest.raises(ModelGroundingValidationError):
        resolve_triage_output(
            output,
            (
                TriageDocumentContext(
                    client_document_id="doc-identity",
                    document_version_id=observation.document_version_id,
                    observations=(observation,),
                    previews_by_page={
                        1: PreviewProvenance(
                            page=1,
                            sha256="e" * 64,
                            transform_version="pymupdf-v1",
                        )
                    },
                ),
            ),
        )


def _observation(observation_id: str, document_version_id: str) -> OcrObservation:
    return OcrObservation(
        observation_id=observation_id,
        document_version_id=UUID(document_version_id),
        page_number=1,
        kind=OcrObservationKind.LINE,
        text="PRESCRIPTION",
        confidence=0.99,
        region=NormalizedRegion(x=0.1, y=0.1, width=0.5, height=0.1),
        source_id=observation_id[:16],
    )
