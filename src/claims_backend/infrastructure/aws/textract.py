import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Protocol

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from claims_backend.application.intelligence import RenderedPage
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.ocr import (
    OcrMalformedResponseError,
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
    OcrProviderError,
    OcrThrottledError,
    OcrTimeoutError,
    TextractProfile,
)


class TextractClient(Protocol):
    def analyze_expense(
        self,
        *,
        Document: dict[str, bytes],
    ) -> Mapping[str, object]: ...

    def analyze_document(
        self,
        *,
        Document: dict[str, bytes],
        FeatureTypes: list[str],
    ) -> Mapping[str, object]: ...

    def detect_document_text(
        self,
        *,
        Document: dict[str, bytes],
    ) -> Mapping[str, object]: ...


class TextractAdapter:
    def __init__(self, client: TextractClient) -> None:
        self._client = client

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        try:
            return self._analyze(page, role)
        except (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError) as error:
            raise OcrTimeoutError("Textract request timed out.") from error
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", "UNKNOWN"))
            metadata = error.response.get("ResponseMetadata", {})
            request_id = (
                str(metadata.get("RequestId"))
                if isinstance(metadata, Mapping) and metadata.get("RequestId")
                else None
            )
            if code in {
                "ThrottlingException",
                "ProvisionedThroughputExceededException",
                "LimitExceededException",
            }:
                raise OcrThrottledError(
                    "Textract throttled the request.",
                    provider_code=code,
                    provider_request_id=request_id,
                ) from error
            status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
            raise OcrProviderError(
                "Textract request failed.",
                retryable=isinstance(status, int) and status >= 500,
                provider_code=code,
                provider_request_id=request_id,
            ) from error
        except ValueError as error:
            raise OcrMalformedResponseError(
                "Textract returned a response that failed project validation."
            ) from error
        except BotoCoreError as error:
            raise OcrProviderError(
                "Textract client failed.",
                retryable=True,
                provider_code=type(error).__name__,
            ) from error

    def _analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        profile = _profile(role)
        if profile is TextractProfile.EXPENSE:
            response = self._client.analyze_expense(Document={"Bytes": page.content})
            observations = _expense_observations(response, page)
        elif profile is TextractProfile.FORMS_TABLES:
            response = self._client.analyze_document(
                Document={"Bytes": page.content},
                FeatureTypes=["FORMS", "TABLES"],
            )
            observations = _block_observations(response, page)
        else:
            response = self._client.detect_document_text(Document={"Bytes": page.content})
            observations = _block_observations(response, page)
        metadata = _mapping(response.get("ResponseMetadata"))
        return OcrPageResult(
            profile=profile,
            provider_request_id=_required_string(metadata, "RequestId"),
            retry_attempts=_integer(metadata.get("RetryAttempts", 0)),
            observations=tuple(
                sorted(
                    observations,
                    key=lambda item: (
                        item.page_number,
                        item.region.y,
                        item.region.x,
                        item.kind.value,
                        item.source_id,
                    ),
                )
            ),
        )


def _profile(role: DocumentRole) -> TextractProfile:
    if role in {DocumentRole.HOSPITAL_BILL, DocumentRole.PHARMACY_BILL}:
        return TextractProfile.EXPENSE
    if role is DocumentRole.UNKNOWN:
        return TextractProfile.TEXT
    return TextractProfile.FORMS_TABLES


def _block_observations(
    response: Mapping[str, object],
    page: RenderedPage,
) -> list[OcrObservation]:
    observations: list[OcrObservation] = []
    for raw in _list(response.get("Blocks")):
        block = _mapping(raw)
        block_type = _required_string(block, "BlockType")
        if block_type not in {"LINE", "WORD"}:
            continue
        source_id = _required_string(block, "Id")
        text = _required_string(block, "Text")
        observations.append(
            _observation(
                page=page,
                kind=OcrObservationKind(block_type),
                text=text,
                confidence=_confidence(block.get("Confidence")),
                region=_region(block.get("Geometry")),
                source_id=source_id,
            )
        )
    return observations


def _expense_observations(
    response: Mapping[str, object],
    page: RenderedPage,
) -> list[OcrObservation]:
    observations: list[OcrObservation] = []
    for expense_index, raw_document in enumerate(_list(response.get("ExpenseDocuments"))):
        document = _mapping(raw_document)
        for field_index, raw_field in enumerate(_list(document.get("SummaryFields"))):
            field = _mapping(raw_field)
            value = _mapping(field.get("ValueDetection"))
            source_id = f"expense:{expense_index}:summary:{field_index}"
            observations.append(
                _observation(
                    page=page,
                    kind=OcrObservationKind.EXPENSE_FIELD,
                    text=_required_string(value, "Text"),
                    confidence=_confidence(value.get("Confidence")),
                    region=_region(value.get("Geometry")),
                    source_id=source_id,
                )
            )
        for group_index, raw_group in enumerate(_list(document.get("LineItemGroups"))):
            group = _mapping(raw_group)
            for line_index, raw_line in enumerate(_list(group.get("LineItems"))):
                line = _mapping(raw_line)
                for field_index, raw_field in enumerate(_list(line.get("LineItemExpenseFields"))):
                    field = _mapping(raw_field)
                    value = _mapping(field.get("ValueDetection"))
                    source_id = (
                        f"expense:{expense_index}:line:{group_index}:{line_index}:{field_index}"
                    )
                    observations.append(
                        _observation(
                            page=page,
                            kind=OcrObservationKind.EXPENSE_FIELD,
                            text=_required_string(value, "Text"),
                            confidence=_confidence(value.get("Confidence")),
                            region=_region(value.get("Geometry")),
                            source_id=source_id,
                        )
                    )
    return observations


def _observation(
    *,
    page: RenderedPage,
    kind: OcrObservationKind,
    text: str,
    confidence: float,
    region: NormalizedRegion,
    source_id: str,
) -> OcrObservation:
    canonical = json.dumps(
        {
            "document_version_id": str(page.document_version_id),
            "page_number": page.page_number,
            "kind": kind.value,
            "text": text,
            "confidence": confidence,
            "region": region.model_dump(mode="json"),
            "source_id": source_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return OcrObservation(
        observation_id=sha256(canonical).hexdigest(),
        document_version_id=page.document_version_id,
        page_number=page.page_number,
        kind=kind,
        text=text,
        confidence=confidence,
        region=region,
        source_id=source_id,
    )


def _region(value: object) -> NormalizedRegion:
    geometry = _mapping(value)
    box = _mapping(geometry.get("BoundingBox"))
    return NormalizedRegion(
        x=_number(box.get("Left")),
        y=_number(box.get("Top")),
        width=_number(box.get("Width")),
        height=_number(box.get("Height")),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Textract response contains an invalid object.")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Textract response contains an invalid list.")
    return value


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"Textract response is missing {key}.")
    return item


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Textract response contains an invalid number.")
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Textract response contains an invalid integer.")
    return value


def _confidence(value: object) -> float:
    return _number(value) / 100
