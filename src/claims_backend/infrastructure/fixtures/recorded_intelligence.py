"""Cost-free deterministic document-intelligence adapters for local operation.

The registry is keyed exclusively by the immutable original document hash.  It
contains synthetic, de-identified fixtures only and is intentionally unable to
inspect a claim ID, case ID, policy outcome, or request metadata.
"""

import json
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class RecordedDocument:
    role: DocumentRole
    readability: str = "READABLE"
    patient_name: str | None = None
    content: dict[str, object] | None = None


class RecordedDiscoveryOcrProvider:
    provider_name = "RECORDED_DISCOVERY_OCR"
    provider_version = "recorded-discovery-v1"

    # Hashes of synthetic JPEGs used by the public operational tracers.
    _records = {
        "ffa497df34d973fa2b30e1cf77d691291f9baa7c219c65fed798a0ccdd893676": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Rajesh Kumar",
            content={
                "date": "2024-11-01",
                "diagnosis": "Synthetic Consultation",
            },
        ),
        "7d61a3141cfc31ff61dff349120e26e493713bbdcc954d039841d5c0b69c34fb": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Rajesh Kumar",
            content={
                "date": "2024-11-01",
                "hospital_name": "Synthetic Hospital",
                "total": 1500,
            },
        ),
        "ce6dd5594d0fda3beba199ec01ec7140ef299b013510b67b9804008dc2431db1": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Rajesh Kumar",
            content={
                "date": "2024-11-01",
                "diagnosis": "Viral Fever",
            },
        ),
        "f9d6d3b2c05a2139b31d04918e207fc3d1578ea99a4f31dcd65e75589ad472c6": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Rajesh Kumar",
            content={
                "date": "2024-11-01",
                "hospital_name": "City Clinic, Bengaluru",
                "line_items": [
                    {"description": "Consultation Fee", "amount": 1000},
                    {"description": "CBC Test", "amount": 300},
                    {"description": "Dengue NS1 Test", "amount": 200},
                ],
                "total": 1500,
            },
        ),
    }

    def analyze(self, page: RenderedPage, role: DocumentRole) -> OcrPageResult:
        document_kind = self._records.get(page.original_sha256)
        if document_kind is None:
            raise RecordedInputUnavailableError(
                "No recorded discovery OCR result exists for this document hash."
            )
        actual_role = document_kind.role
        if role not in {DocumentRole.UNKNOWN, actual_role}:
            raise RecordedInputUnavailableError(
                "Recorded role-aware OCR has no result for the requested document role."
            )
        observation_id = sha256(
            (
                f"{page.document_version_id}:{page.original_sha256}:"
                f"{page.page_number}:{role.value}:recorded-discovery-v1"
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
                    text=_recorded_ocr_text(document_kind),
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
            record = _record_from_observations(observations)
            role = _role_from_observations(observations)
            identity_observations: list[dict[str, object]] = []
            if record is not None and record.patient_name is not None:
                identity_observations.append(
                    {
                        "kind": "PATIENT_NAME",
                        "value": record.patient_name,
                        "page": 1,
                        "region": {"x": 0.05, "y": 0.1, "width": 0.9, "height": 0.2},
                        "source_text_sha256": sha256(record.patient_name.encode()).hexdigest(),
                        "confidence": 0.99,
                    }
                )
            output_documents.append(
                {
                    "client_document_id": client_document_id,
                    "role": role.value,
                    "readability": {
                        "status": ("READABLE" if record is None else record.readability),
                        "preview": {
                            "page": 1,
                            "sha256": sha256(canonical_observations.encode()).hexdigest(),
                            "transform_version": "recorded-discovery-v1",
                        },
                    },
                    "identity_observations": identity_observations,
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
    record = _record_from_observations(observations)
    if record is not None:
        return record.role
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
    record = _record_from_observations(observations)
    role = _role_from_observations(observations)
    observation_id = (
        observations[0].get("observation_id") if isinstance(observations[0], dict) else None
    )
    if not isinstance(observation_id, str):
        raise RecordedInputUnavailableError("Recorded extraction observation is invalid.")
    values = _extraction_values(record, role)
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


def _recorded_ocr_text(record: RecordedDocument) -> str:
    return "RECORDED_DOCUMENT:" + json.dumps(
        {
            "role": record.role.value,
            "readability": record.readability,
            "patient_name": record.patient_name,
            "content": record.content or {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _record_from_observations(observations: list[object]) -> RecordedDocument | None:
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        text = observation.get("text")
        if not isinstance(text, str) or not text.startswith("RECORDED_DOCUMENT:"):
            continue
        payload = cast(dict[str, object], json.loads(text.removeprefix("RECORDED_DOCUMENT:")))
        role = payload.get("role")
        readability = payload.get("readability")
        patient_name = payload.get("patient_name")
        content = payload.get("content")
        if not isinstance(role, str) or not isinstance(readability, str):
            raise RecordedInputUnavailableError("Recorded OCR payload is invalid.")
        return RecordedDocument(
            role=DocumentRole(role),
            readability=readability,
            patient_name=patient_name if isinstance(patient_name, str) else None,
            content=content if isinstance(content, dict) else None,
        )
    return None


def _extraction_values(
    record: RecordedDocument | None,
    role: DocumentRole,
) -> tuple[tuple[str, str], ...]:
    if record is None:
        return (
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
    if record.content is None:
        return ()
    values: list[tuple[str, str]] = []
    if record.patient_name is not None:
        values.append(("patient.name", record.patient_name))
    content = record.content
    date = content.get("date")
    if isinstance(date, str):
        values.append(("treatment.date", date))
    diagnosis = content.get("diagnosis")
    if isinstance(diagnosis, str):
        values.append(("clinical.condition", diagnosis))
    provider = content.get("hospital_name")
    if isinstance(provider, str):
        values.append(("provider.name", provider))
    total = content.get("total")
    if isinstance(total, int | float):
        values.append(("billing.total", f"{float(total):.2f}"))
    if role is DocumentRole.HOSPITAL_BILL:
        line_items = content.get("line_items")
        if isinstance(line_items, list):
            for item in line_items:
                if not isinstance(item, dict):
                    continue
                description, amount = item.get("description"), item.get("amount")
                if isinstance(description, str) and isinstance(amount, int | float):
                    values.append(
                        (
                            f"billing.line_items.{_slug(description)}",
                            f"{float(amount):.2f}",
                        )
                    )
    return tuple(values)


def _slug(value: str) -> str:
    return "_".join(
        "".join(char for char in part if char.isalnum()).casefold() for part in value.split()
    )
