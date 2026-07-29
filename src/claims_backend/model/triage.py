import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from claims_backend.domain.evidence import (
    DocumentRole,
    PreviewProvenance,
    Readability,
    ReadabilityObservation,
    ResolvedTriageOutput,
    TriageDocumentResult,
    TriageEvidenceField,
    TriageEvidenceNormalizationReport,
    TriageIdentityObservation,
    TriageModelOutput,
    TriageProviderOutputV4,
)
from claims_backend.domain.extraction import ModelGroundingValidationError
from claims_backend.domain.ocr import OcrObservation
from claims_backend.model.evidence_normalization import (
    EvidenceReferencePolicy,
    normalize_evidence_references,
)


@dataclass(frozen=True, slots=True)
class TriageDocumentContext:
    """Backend-owned evidence available while resolving one document prediction."""

    client_document_id: str
    document_version_id: UUID
    observations: tuple[OcrObservation, ...]
    previews_by_page: Mapping[int, PreviewProvenance]


@dataclass(frozen=True, slots=True)
class TriageResolution:
    output: ResolvedTriageOutput
    normalization_reports: dict[str, TriageEvidenceNormalizationReport]


def resolve_triage_output(
    output: TriageModelOutput | TriageProviderOutputV4 | None,
    contexts: tuple[TriageDocumentContext, ...],
) -> ResolvedTriageOutput:
    """Turn untrusted semantic predictions into fully provenanced triage results."""

    return resolve_triage_with_reports(output, contexts, policy=None).output


def resolve_triage_with_reports(
    output: TriageModelOutput | TriageProviderOutputV4 | None,
    contexts: tuple[TriageDocumentContext, ...],
    *,
    policy: EvidenceReferencePolicy | None,
) -> TriageResolution:
    """Resolve output and produce v4 normalization audit data when applicable."""

    contexts_by_id = _index_contexts(contexts)
    output_documents = () if output is None else output.documents
    predictions_by_id = {document.client_document_id: document for document in output_documents}
    expected_prediction_ids = {
        client_document_id
        for client_document_id, context in contexts_by_id.items()
        if context.observations
    }
    if (
        len(predictions_by_id) != len(output_documents)
        or set(predictions_by_id) != expected_prediction_ids
    ):
        raise ModelGroundingValidationError(
            "Triage output must cover each document with OCR observations exactly once."
        )

    documents: list[TriageDocumentResult] = []
    reports: dict[str, TriageEvidenceNormalizationReport] = {}
    for client_document_id, context in contexts_by_id.items():
        if not context.observations:
            preview = _first_preview(context)
            documents.append(
                TriageDocumentResult(
                    client_document_id=client_document_id,
                    role=DocumentRole.UNKNOWN,
                    readability=ReadabilityObservation(
                        status=Readability.UNREADABLE,
                        preview=preview,
                    ),
                    identity_observations=(),
                )
            )
            continue
        prediction = predictions_by_id[client_document_id]
        observations_by_id = _index_observations(context)
        if isinstance(output, TriageProviderOutputV4):
            if policy is None:
                raise ValueError("A v4 triage output requires an evidence reference policy.")
            available_ids = frozenset(observations_by_id)
            role_normalization = normalize_evidence_references(
                prediction.role_evidence_refs,
                field=TriageEvidenceField.ROLE,
                available_observation_ids=available_ids,
                policy=policy,
            )
            readability_normalization = normalize_evidence_references(
                prediction.readability_evidence_refs,
                field=TriageEvidenceField.READABILITY,
                available_observation_ids=available_ids,
                policy=policy,
            )
            role_refs = role_normalization.retained_refs
            readability_refs = readability_normalization.retained_refs
            reports[prediction.client_document_id] = TriageEvidenceNormalizationReport(
                policy_version=policy.version,
                role=role_normalization,
                readability=readability_normalization,
            )
        else:
            _resolve_references(prediction.role_evidence_refs, observations_by_id)
            _resolve_references(prediction.readability_evidence_refs, observations_by_id)
            role_refs = prediction.role_evidence_refs
            readability_refs = prediction.readability_evidence_refs
        readability_observations = _resolve_references(readability_refs, observations_by_id)
        preview_page = readability_observations[0].page_number
        resolved_preview = context.previews_by_page.get(preview_page)
        if resolved_preview is None:
            raise TriageProvenanceResolutionError(
                "The referenced OCR page has no backend preview provenance."
            )

        identities: list[TriageIdentityObservation] = []
        for selection in prediction.identity_observations:
            observation = _resolve_references(
                (selection.observation_id,),
                observations_by_id,
            )[0]
            if _normalize(selection.value) not in _normalize(observation.text):
                raise ModelGroundingValidationError(
                    "Triage identity value is not grounded in its referenced OCR text."
                )
            identities.append(
                TriageIdentityObservation(
                    kind=selection.kind,
                    value=selection.value,
                    observation_id=observation.observation_id,
                    page=observation.page_number,
                    region=observation.region,
                    source_text_sha256=sha256(observation.text.encode()).hexdigest(),
                    confidence=observation.confidence,
                )
            )

        documents.append(
            TriageDocumentResult(
                client_document_id=client_document_id,
                role=prediction.role,
                role_evidence_refs=role_refs,
                readability=ReadabilityObservation(
                    status=prediction.readability,
                    preview=resolved_preview,
                ),
                readability_evidence_refs=readability_refs,
                identity_observations=tuple(identities),
            )
        )
    return TriageResolution(
        output=ResolvedTriageOutput(documents=tuple(documents)),
        normalization_reports=reports,
    )


def _index_contexts(
    contexts: tuple[TriageDocumentContext, ...],
) -> dict[str, TriageDocumentContext]:
    indexed = {context.client_document_id: context for context in contexts}
    if not indexed or len(indexed) != len(contexts):
        raise ValueError("Triage contexts must be non-empty and uniquely identified.")
    return indexed


def _index_observations(context: TriageDocumentContext) -> dict[str, OcrObservation]:
    indexed: dict[str, OcrObservation] = {}
    for observation in context.observations:
        if observation.document_version_id != context.document_version_id:
            raise ValueError("OCR observation belongs to a different document version.")
        if observation.observation_id in indexed:
            raise ValueError("OCR observations must have unique identifiers.")
        indexed[observation.observation_id] = observation
    return indexed


def _resolve_references(
    references: tuple[str, ...],
    observations_by_id: Mapping[str, OcrObservation],
) -> tuple[OcrObservation, ...]:
    if len(set(references)) != len(references):
        raise ModelGroundingValidationError("Triage evidence references must be unique.")
    try:
        return tuple(observations_by_id[reference] for reference in references)
    except KeyError as error:
        raise ModelGroundingValidationError(
            "Triage output references an unavailable OCR observation."
        ) from error


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _first_preview(context: TriageDocumentContext) -> PreviewProvenance:
    if not context.previews_by_page:
        raise TriageProvenanceResolutionError(
            "A document cannot be triaged without backend preview provenance."
        )
    return context.previews_by_page[min(context.previews_by_page)]


class TriageProvenanceResolutionError(RuntimeError):
    pass
