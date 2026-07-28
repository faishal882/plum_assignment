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
        "7e7f6c08d420e0e6c1b383441be9850db2662c7ffe49f353700437cbbd381955": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Vikram Joshi",
            content={
                "date": "2024-10-15",
                "diagnosis": "Type 2 Diabetes Mellitus",
            },
        ),
        "540606661182a6f7c5c183d9d8e1f87f4772bb8f2dedc98361ca531f2a65b40c": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Vikram Joshi",
            content={"date": "2024-10-15", "total": 3000},
        ),
        "7baa52debefd2f42120ccb649ffc37a52ee27dfba15159d22b424112b78beb4c": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Priya Singh",
            content={
                "date": "2024-10-15",
                "hospital_name": "Smile Dental Clinic",
                "line_items": [
                    {"description": "Root Canal Treatment", "amount": 8000},
                    {"description": "Teeth Whitening", "amount": 4000},
                ],
                "total": 12000,
            },
        ),
        "4b40289a4779b19fb3487c93105ce0210787c34a1153af53b8e0623b37a121ee": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Suresh Patil",
            content={
                "date": "2024-11-02",
                "diagnosis": "Suspected Lumbar Disc Herniation",
                "tests_ordered": ["MRI Lumbar Spine"],
            },
        ),
        "4434347caee415c76c08ce97736e44e6ddddfd4e6d289dad2787f7b97d7249da": RecordedDocument(
            DocumentRole.LAB_REPORT,
            content={"test_name": "MRI Lumbar Spine"},
        ),
        "b5b677ae00fc83c81d0967eca4dc22c3e56920571095fb7e69fba611dd6ff97d": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Suresh Patil",
            content={
                "date": "2024-11-02",
                "line_items": [{"description": "MRI Lumbar Spine", "amount": 15000}],
                "total": 15000,
            },
        ),
        "794f357edfa5309d8ee9ab291978d954690066af7f1a25e2c317bf431dcf1116": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Amit Verma",
            content={"date": "2024-10-20", "diagnosis": "Gastroenteritis"},
        ),
        "339da8a6a604c73cad1f49be0bb6141063e5e86552d9a85e842171f3014f75d2": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Amit Verma",
            content={
                "date": "2024-10-20",
                "line_items": [
                    {"description": "Consultation Fee", "amount": 2000},
                    {"description": "Medicines", "amount": 5500},
                ],
                "total": 7500,
            },
        ),
        "ad8823e89fa4d72725ba67c491921dbcaaf453d896dd3e21cb48b614682ee2a7": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Ravi Menon",
            content={"date": "2024-10-30", "diagnosis": "Migraine"},
        ),
        "29732a9119b59785d6e21b29686ac66e9b4552c8ad44319ad68b2bfccafe079d": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Ravi Menon",
            content={"date": "2024-10-30", "total": 4800},
        ),
        "dfa961a94a1ef140ffd34a828291addb1e668da05f8420df429586544d165d20": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Deepak Shah",
            content={"date": "2024-11-03", "diagnosis": "Acute Bronchitis"},
        ),
        "d36653736568ef358aa6a99c3693d1c811e322dba52c243cc6323fa9a235a1d3": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Deepak Shah",
            content={
                "date": "2024-11-03",
                "hospital_name": "Apollo Hospitals",
                "line_items": [
                    {"description": "Consultation Fee", "amount": 1500},
                    {"description": "Medicines", "amount": 3000},
                ],
                "total": 4500,
            },
        ),
        "e45c76002c0b4a8604e7314aee3c036ce1034cb0d4b3a379d8ba3ce442433ec4": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Kavita Nair",
            content={
                "date": "2024-10-28",
                "diagnosis": "Chronic Joint Pain",
                "treatment": "Panchakarma Therapy",
            },
        ),
        "b4cb7ba36fadf8b349c24f5b1dc2505bac15fab7d2f22ce50282893b763f1124": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Kavita Nair",
            content={
                "date": "2024-10-28",
                "hospital_name": "Ayur Wellness Centre",
                "line_items": [
                    {"description": "Panchakarma Therapy 5 sessions", "amount": 3000},
                    {"description": "Consultation", "amount": 1000},
                ],
                "total": 4000,
            },
        ),
        "f7a2d6ecf9ff78e56031399b1690ae71e1df553322142e4728bcd0aca64931ae": RecordedDocument(
            DocumentRole.PRESCRIPTION,
            patient_name="Anita Desai",
            content={
                "date": "2024-10-18",
                "diagnosis": "Morbid Obesity BMI 37",
                "treatment": "Bariatric Consultation and Customised Diet Plan",
            },
        ),
        "10513dcf9a8a66f6c7c01d1a0bf9f012075e33671b720ac5359d7a86368b8218": RecordedDocument(
            DocumentRole.HOSPITAL_BILL,
            patient_name="Anita Desai",
            content={
                "date": "2024-10-18",
                "line_items": [
                    {"description": "Bariatric Consultation", "amount": 3000},
                    {"description": "Personalised Diet and Nutrition Program", "amount": 5000},
                ],
                "total": 8000,
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
    treatment = content.get("treatment") or content.get("test_name")
    if treatment is None:
        ordered = content.get("tests_ordered")
        if isinstance(ordered, list) and ordered and isinstance(ordered[0], str):
            treatment = ordered[0]
    if isinstance(treatment, str):
        values.append(("clinical.treatment", "MRI" if "mri" in treatment.casefold() else treatment))
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
