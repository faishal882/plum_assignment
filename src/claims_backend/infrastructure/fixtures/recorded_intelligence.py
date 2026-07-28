"""Cost-free deterministic document-intelligence adapters for local operation.

The registry is keyed exclusively by the immutable original document hash.  It
contains synthetic, de-identified fixtures only and is intentionally unable to
inspect a claim ID, case ID, policy outcome, or request metadata.
"""

import json
from hashlib import sha256
from typing import cast

from pydantic import BaseModel

from claims_backend.application.intelligence import RenderedPage
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    TextractProfile,
)
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation


class RecordedInputUnavailableError(RuntimeError):
    """Raised when a local recorded profile has no approved input recording."""


class RecordedDiscoveryOcrProvider:
    provider_name = "RECORDED_DISCOVERY_OCR"
    provider_version = "recorded-discovery-v1"

    # Hashes of synthetic JPEGs used by the public operational tracers.
    _records = {
        "ffa497df34d973fa2b30e1cf77d691291f9baa7c219c65fed798a0ccdd893676": "PRESCRIPTION",
        "7d61a3141cfc31ff61dff349120e26e493713bbdcc954d039841d5c0b69c34fb": "HOSPITAL_BILL",
    }

    def analyze(self, page: RenderedPage, role: DocumentRole) -> OcrPageResult:
        if role is not DocumentRole.UNKNOWN:
            raise RecordedInputUnavailableError(
                "Recorded discovery OCR accepts only the UNKNOWN discovery role."
            )
        document_kind = self._records.get(page.original_sha256)
        if document_kind is None:
            raise RecordedInputUnavailableError(
                "No recorded discovery OCR result exists for this document hash."
            )
        observation_id = sha256(
            (
                f"{page.document_version_id}:{page.original_sha256}:"
                f"{page.page_number}:recorded-discovery-v1"
            ).encode()
        ).hexdigest()
        return OcrPageResult(
            profile=TextractProfile.TEXT,
            provider_request_id=f"recorded-{page.original_sha256[:24]}",
            retry_attempts=0,
            observations=(
                OcrObservation(
                    observation_id=observation_id,
                    document_version_id=page.document_version_id,
                    page_number=page.page_number,
                    kind=OcrObservationKind.LINE,
                    text=f"Synthetic recorded {document_kind} document.",
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.2),
                    source_id="recorded-discovery-line-1",
                ),
            ),
        )


class RecordedDocumentModelTransport:
    """Recorded local responses derived only from bounded OCR observations."""

    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        del schema
        if len(messages) != 2 or messages[1][0] != "human":
            raise RecordedInputUnavailableError("Recorded model input is invalid.")
        if config.route is ModelRoute.COMPLEX_EXTRACTION:
            raw_output = _complex_extraction(messages[1][1])
            return _invocation(raw_output)
        if config.route is not ModelRoute.FAST_TRIAGE:
            raise RecordedInputUnavailableError("Recorded model route is unsupported.")
        payload = cast(dict[str, object], json.loads(messages[1][1]))
        documents = payload.get("documents")
        if not isinstance(documents, list) or not documents:
            raise RecordedInputUnavailableError("Recorded triage input has no documents.")
        output_documents: list[dict[str, object]] = []
        for document in documents:
            if not isinstance(document, dict):
                raise RecordedInputUnavailableError("Recorded triage document is invalid.")
            client_document_id = document.get("client_document_id")
            observations = document.get("observations")
            if not isinstance(client_document_id, str) or not isinstance(observations, list):
                raise RecordedInputUnavailableError("Recorded triage document is incomplete.")
            canonical_observations = json.dumps(
                observations,
                sort_keys=True,
                separators=(",", ":"),
            )
            role = _role_from_observations(observations)
            output_documents.append(
                {
                    "client_document_id": client_document_id,
                    "role": role.value,
                    "readability": {
                        "status": "READABLE",
                        "preview": {
                            "page": 1,
                            "sha256": sha256(canonical_observations.encode()).hexdigest(),
                            "transform_version": "recorded-discovery-v1",
                        },
                    },
                    "identity_observations": [],
                }
            )
        raw_output = {"schema_version": 2, "documents": output_documents}
        return _invocation(raw_output)


def _invocation(raw_output: dict[str, object]) -> ModelInvocation:
    request_key = json.dumps(raw_output, sort_keys=True, separators=(",", ":")).encode()
    return ModelInvocation(
        raw_output=raw_output,
        provider_request_id=f"recorded-{sha256(request_key).hexdigest()[:24]}",
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        stop_reason="RECORDED",
    )


def _role_from_observations(observations: list[object]) -> DocumentRole:
    text = json.dumps(observations, sort_keys=True).upper()
    if "HOSPITAL_BILL" in text:
        return DocumentRole.HOSPITAL_BILL
    if "PRESCRIPTION" in text:
        return DocumentRole.PRESCRIPTION
    return DocumentRole.UNKNOWN


def _complex_extraction(message: str) -> dict[str, object]:
    payload = cast(dict[str, object], json.loads(message))
    observations = payload.get("ocr_observations")
    if not isinstance(observations, list) or not observations:
        raise RecordedInputUnavailableError("Recorded extraction input has no observations.")
    role = _role_from_observations(observations)
    observation_id = (
        observations[0].get("observation_id") if isinstance(observations[0], dict) else None
    )
    if not isinstance(observation_id, str):
        raise RecordedInputUnavailableError("Recorded extraction observation is invalid.")
    values = (
        (
            ("patient.name", "Rajesh Kumar"),
            ("treatment.date", "2024-11-01"),
            ("clinical.condition", "Synthetic Consultation"),
        )
        if role is DocumentRole.PRESCRIPTION
        else (
            ("patient.name", "Rajesh Kumar"),
            ("treatment.date", "2024-11-01"),
            ("billing.total", "1500.00"),
            ("provider.name", "Synthetic Hospital"),
        )
        if role is DocumentRole.HOSPITAL_BILL
        else ()
    )
    if not values:
        raise RecordedInputUnavailableError(
            "No recorded extraction result exists for this OCR input."
        )
    return {
        "schema_version": "complex-extraction-v1",
        "candidates": [
            {
                "fact_path": path,
                "value": value,
                "normalized_value": value,
                "evidence_refs": [observation_id],
                "confidence": 0.99,
            }
            for path, value in values
        ],
    }
