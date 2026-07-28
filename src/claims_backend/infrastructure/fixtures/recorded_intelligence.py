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

    # Hash of the synthetic blank JPEG used by the public operational tracer.
    _records = {
        "ffa497df34d973fa2b30e1cf77d691291f9baa7c219c65fed798a0ccdd893676": (
            "Synthetic recorded prescription document."
        )
    }

    def analyze(self, page: RenderedPage, role: DocumentRole) -> OcrPageResult:
        if role is not DocumentRole.UNKNOWN:
            raise RecordedInputUnavailableError(
                "Recorded discovery OCR accepts only the UNKNOWN discovery role."
            )
        text = self._records.get(page.original_sha256)
        if text is None:
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
                    text=text,
                    confidence=0.99,
                    region=NormalizedRegion(x=0.05, y=0.1, width=0.9, height=0.2),
                    source_id="recorded-discovery-line-1",
                ),
            ),
        )


class RecordedDocumentModelTransport:
    """Recorded local triage responses derived only from submitted OCR inputs."""

    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        del schema
        if config.route is not ModelRoute.FAST_TRIAGE:
            raise RecordedInputUnavailableError(
                "No recorded complex-extraction result exists for this input."
            )
        if len(messages) != 2 or messages[1][0] != "human":
            raise RecordedInputUnavailableError("Recorded triage input is invalid.")
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
            output_documents.append(
                {
                    "client_document_id": client_document_id,
                    "role": DocumentRole.PRESCRIPTION.value,
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
        raw_output: dict[str, object] = {"schema_version": 2, "documents": output_documents}
        request_key = json.dumps(raw_output, sort_keys=True, separators=(",", ":")).encode()
        return ModelInvocation(
            raw_output=raw_output,
            provider_request_id=f"recorded-{sha256(request_key).hexdigest()[:24]}",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            stop_reason="RECORDED",
        )
