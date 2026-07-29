import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from threading import BoundedSemaphore
from typing import Protocol, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from openinference.semconv.trace import OpenInferenceSpanKindValues

from claims_backend.application.intelligence import RenderedPage
from claims_backend.config import Settings
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
from claims_backend.observability import EngineeringLogEvent, Observability


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
    provider_name = "AMAZON_TEXTRACT"
    provider_version = "boto3-textract-v1"

    def __init__(
        self,
        client: TextractClient,
        *,
        concurrency_limit: int = 2,
        observability: Observability | None = None,
    ) -> None:
        if concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be greater than zero")
        self._client = client
        self._permit = BoundedSemaphore(concurrency_limit)
        self._observability = observability

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        if self._observability is None:
            return self._analyze_with_errors(page, role)
        profile = _profile(role)
        with self._observability.span(
            "textract.analyze_page",
            component="textract",
            span_kind=OpenInferenceSpanKindValues.TOOL.value,
            attributes={
                "provider.name": self.provider_name,
                "textract.profile": profile.value,
                "textract.page_number": page.page_number,
            },
        ) as span:
            try:
                result = self._analyze_with_errors(page, role)
            except Exception as error:
                self._observability.log(
                    EngineeringLogEvent(
                        event_name="textract_request_failed",
                        component="textract",
                        outcome="ERROR",
                        duration_ms=0,
                        provider_name=self.provider_name,
                        error_type=type(error).__name__,
                    )
                )
                raise
            self._observability.set_attributes(
                span,
                {
                    "provider.request_id": result.provider_request_id,
                    "provider.retry_count": result.retry_attempts,
                    "textract.observation_count": len(result.observations),
                },
            )
            self._observability.log(
                EngineeringLogEvent(
                    event_name="textract_request_finished",
                    component="textract",
                    outcome="OK",
                    duration_ms=0,
                    provider_name=self.provider_name,
                    provider_request_id=result.provider_request_id,
                )
            )
            return result

    def _analyze_with_errors(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult:
        try:
            with self._permit:
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
            observations = _expense_observations(response, page, role)
        elif profile is TextractProfile.FORMS_TABLES:
            response = self._client.analyze_document(
                Document={"Bytes": page.content},
                FeatureTypes=["FORMS", "TABLES"],
            )
            observations = _block_observations(response, page, role)
        else:
            response = self._client.detect_document_text(Document={"Bytes": page.content})
            observations = _block_observations(response, page, role)
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


def create_textract_client(
    *,
    region: str,
    read_timeout_seconds: int = 30,
    client_factory: Callable[..., object] | None = None,
) -> TextractClient:
    if not region:
        raise ValueError("region cannot be empty")
    if read_timeout_seconds <= 0:
        raise ValueError("read_timeout_seconds must be greater than zero")
    factory = client_factory or boto3.client
    return cast(
        TextractClient,
        factory(
            "textract",
            region_name=region,
            config=BotoConfig(
                connect_timeout=30,
                read_timeout=read_timeout_seconds,
                retries={
                    # Workflow retries are durable and auditable; do not hide attempts here.
                    "total_max_attempts": 1,
                    "mode": "standard",
                },
            ),
        ),
    )


def textract_adapter_from_settings(
    settings: Settings,
    *,
    client_factory: Callable[..., object] | None = None,
    observability: Observability | None = None,
) -> TextractAdapter:
    return TextractAdapter(
        create_textract_client(
            region=settings.aws_region,
            read_timeout_seconds=settings.textract_timeout_seconds,
            client_factory=client_factory,
        ),
        concurrency_limit=settings.textract_concurrency_limit,
        observability=observability,
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
    role: DocumentRole,
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
                role=role,
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
    role: DocumentRole,
) -> list[OcrObservation]:
    observations: list[OcrObservation] = []
    for expense_index, raw_document in enumerate(_list(response.get("ExpenseDocuments"))):
        document = _mapping(raw_document)
        for field_index, raw_field in enumerate(_list(document.get("SummaryFields"))):
            field = _mapping(raw_field)
            field_type = _expense_field_type(field)
            value = _mapping(field.get("ValueDetection"))
            source_id = f"expense:{expense_index}:summary:{field_index}"
            observations.append(
                _observation(
                    page=page,
                    role=role,
                    kind=OcrObservationKind.EXPENSE_FIELD,
                    text=_required_string(value, "Text"),
                    confidence=_confidence(value.get("Confidence")),
                    region=_region(value.get("Geometry")),
                    source_id=source_id,
                    field_type=field_type,
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
                            role=role,
                            kind=OcrObservationKind.EXPENSE_FIELD,
                            text=_required_string(value, "Text"),
                            confidence=_confidence(value.get("Confidence")),
                            region=_region(value.get("Geometry")),
                            source_id=source_id,
                            field_type=_expense_field_type(field),
                        )
                    )
    return observations


def _observation(
    *,
    page: RenderedPage,
    role: DocumentRole,
    kind: OcrObservationKind,
    text: str,
    confidence: float,
    region: NormalizedRegion,
    source_id: str,
    field_type: str | None = None,
) -> OcrObservation:
    canonical = json.dumps(
        {
            "document_version_id": str(page.document_version_id),
            "document_role": role.value,
            "page_number": page.page_number,
            "kind": kind.value,
            "text": text,
            "confidence": confidence,
            "region": region.model_dump(mode="json"),
            "source_id": source_id,
            "field_type": field_type,
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
        field_type=field_type,
    )


def _expense_field_type(field: Mapping[str, object]) -> str | None:
    """Return Textract's immutable semantic label when the provider supplied one."""
    raw_type = field.get("Type")
    if raw_type is None:
        return None
    field_type = _mapping(raw_type).get("Text")
    if not isinstance(field_type, str) or not field_type.strip():
        return None
    return field_type.strip().upper()


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
