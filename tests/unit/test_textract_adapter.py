from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock, patch
from uuid import UUID

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.stub import Stubber
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from claims_backend.application.intelligence import RenderedPage
from claims_backend.domain.evidence import DocumentRole
from claims_backend.domain.ocr import (
    OcrMalformedResponseError,
    OcrProviderError,
    OcrThrottledError,
    OcrTimeoutError,
    TextractProfile,
)
from claims_backend.infrastructure.aws.textract import TextractAdapter, create_textract_client
from claims_backend.observability import ObservabilityConfig, create_observability


def test_textract_profiles_send_page_bytes_and_map_project_observations(
    tmp_path: Path,
) -> None:
    client = _client()
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=exporter,
    )
    adapter = TextractAdapter(client, observability=observability)
    page = _page()
    with Stubber(client) as stubber:
        stubber.add_response(
            "analyze_expense",
            _expense_response(),
            {"Document": {"Bytes": page.content}},
        )
        stubber.add_response(
            "analyze_document",
            _blocks_response("analyze-1"),
            {
                "Document": {"Bytes": page.content},
                "FeatureTypes": ["FORMS", "TABLES"],
            },
        )
        stubber.add_response(
            "detect_document_text",
            _blocks_response("text-1"),
            {"Document": {"Bytes": page.content}},
        )

        expense = adapter.analyze(page, DocumentRole.PHARMACY_BILL)
        forms = adapter.analyze(page, DocumentRole.PRESCRIPTION)
        text = adapter.analyze(page, DocumentRole.UNKNOWN)

    assert expense.profile is TextractProfile.EXPENSE
    assert forms.profile is TextractProfile.FORMS_TABLES
    assert text.profile is TextractProfile.TEXT
    assert expense.provider_request_id == "expense-1"
    assert expense.observations[0].text == "800.00"
    assert expense.observations[0].page_number == 1
    assert expense.observations[0].document_version_id == page.document_version_id
    assert expense.observations[0].region.model_dump() == {
        "x": 0.1,
        "y": 0.2,
        "width": 0.3,
        "height": 0.1,
    }
    assert forms.observations[0].text == "Patient: Rajesh Kumar"
    assert text.observations == forms.observations
    observability.shutdown()
    spans = exporter.get_finished_spans()
    assert [span.attributes["textract.profile"] for span in spans] == [
        "EXPENSE",
        "FORMS_TABLES",
        "TEXT",
    ]
    assert [span.attributes["provider.request_id"] for span in spans] == [
        "expense-1",
        "analyze-1",
        "text-1",
    ]
    assert all("ocr_text" not in span.attributes for span in spans)


def test_malformed_textract_response_has_a_non_retryable_typed_failure() -> None:
    client = _client()
    adapter = TextractAdapter(client)
    page = _page()
    with Stubber(client) as stubber:
        stubber.add_response(
            "detect_document_text",
            {
                "DocumentMetadata": {"Pages": 1},
                "Blocks": [{"BlockType": "LINE", "Id": "line-without-content"}],
                "ResponseMetadata": {
                    "RequestId": "malformed-1",
                    "HTTPStatusCode": 200,
                    "HTTPHeaders": {},
                    "RetryAttempts": 0,
                },
            },
            {"Document": {"Bytes": page.content}},
        )

        with pytest.raises(OcrMalformedResponseError) as captured:
            adapter.analyze(page, DocumentRole.UNKNOWN)

    assert captured.value.code == "TEXTRACT_MALFORMED_RESPONSE"
    assert captured.value.retryable is False


def test_textract_service_errors_preserve_retryability() -> None:
    client = _client()
    adapter = TextractAdapter(client)
    page = _page()
    with Stubber(client) as stubber:
        stubber.add_client_error(
            "detect_document_text",
            service_error_code="ThrottlingException",
            service_message="rate exceeded",
            http_status_code=400,
            expected_params={"Document": {"Bytes": page.content}},
        )
        with pytest.raises(OcrThrottledError) as throttled:
            adapter.analyze(page, DocumentRole.UNKNOWN)

    assert throttled.value.code == "TEXTRACT_THROTTLED"
    assert throttled.value.retryable is True

    with Stubber(client) as stubber:
        stubber.add_client_error(
            "detect_document_text",
            service_error_code="AccessDeniedException",
            service_message="denied",
            http_status_code=403,
            expected_params={"Document": {"Bytes": page.content}},
        )
        with pytest.raises(OcrProviderError) as denied:
            adapter.analyze(page, DocumentRole.UNKNOWN)

    assert denied.value.code == "TEXTRACT_PROVIDER_ERROR"
    assert denied.value.retryable is False


def test_textract_timeout_is_a_retryable_typed_failure() -> None:
    client = _client()
    adapter = TextractAdapter(client)
    with patch.object(
        client,
        "detect_document_text",
        side_effect=ReadTimeoutError(endpoint_url="https://textract.ap-south-1.amazonaws.com"),
    ):
        with pytest.raises(OcrTimeoutError) as captured:
            adapter.analyze(_page(), DocumentRole.UNKNOWN)

    assert captured.value.code == "TEXTRACT_TIMEOUT"
    assert captured.value.retryable is True


def test_textract_client_applies_configured_timeout_and_attempt_limit() -> None:
    factory = Mock()

    create_textract_client(
        region="ap-south-1",
        read_timeout_seconds=31,
        client_factory=factory,
    )

    factory.assert_called_once()
    assert factory.call_args.args == ("textract",)
    assert factory.call_args.kwargs["region_name"] == "ap-south-1"
    provider_config = factory.call_args.kwargs["config"]
    assert provider_config.read_timeout == 31
    assert provider_config.retries["total_max_attempts"] == 1


def test_textract_adapter_bounds_concurrent_provider_calls() -> None:
    release = Event()
    two_started = Event()
    lock = Lock()
    active = 0
    maximum_active = 0

    class BlockingClient:
        def detect_document_text(self, *, Document):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                if active == 2:
                    two_started.set()
            assert release.wait(timeout=2)
            with lock:
                active -= 1
            return _blocks_response("bounded-request")

    adapter = TextractAdapter(BlockingClient())
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(adapter.analyze, _page(), DocumentRole.UNKNOWN)
            for _ in range(3)
        ]
        assert two_started.wait(timeout=2)
        assert maximum_active == 2
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert maximum_active == 2


def _client():
    return boto3.client(
        "textract",
        region_name="ap-south-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(retries={"max_attempts": 0}),
    )


def _page() -> RenderedPage:
    content = b"synthetic-jpeg-page"
    return RenderedPage(
        document_id=UUID("00000000-0000-0000-0000-000000000101"),
        document_version_id=UUID("00000000-0000-0000-0000-000000000201"),
        page_number=1,
        original_sha256="a" * 64,
        media_type="image/jpeg",
        content=content,
        sha256="b" * 64,
        size_bytes=len(content),
        width=100,
        height=100,
        render_version="test-render-v1",
    )


def _geometry() -> dict[str, object]:
    return {
        "BoundingBox": {
            "Width": 0.3,
            "Height": 0.1,
            "Left": 0.1,
            "Top": 0.2,
        },
        "Polygon": [
            {"X": 0.1, "Y": 0.2},
            {"X": 0.4, "Y": 0.2},
            {"X": 0.4, "Y": 0.3},
            {"X": 0.1, "Y": 0.3},
        ],
    }


def _blocks_response(request_id: str) -> dict[str, object]:
    return {
        "DocumentMetadata": {"Pages": 1},
        "Blocks": [
            {
                "BlockType": "LINE",
                "Id": "line-1",
                "Text": "Patient: Rajesh Kumar",
                "Confidence": 98.5,
                "Geometry": _geometry(),
                "Page": 1,
            }
        ],
        "ResponseMetadata": {
            "RequestId": request_id,
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
            "RetryAttempts": 0,
        },
    }


def _expense_response() -> dict[str, object]:
    return {
        "DocumentMetadata": {"Pages": 1},
        "ExpenseDocuments": [
            {
                "ExpenseIndex": 1,
                "SummaryFields": [
                    {
                        "Type": {"Text": "TOTAL", "Confidence": 99.0},
                        "ValueDetection": {
                            "Text": "800.00",
                            "Confidence": 98.0,
                            "Geometry": _geometry(),
                        },
                        "PageNumber": 1,
                    }
                ],
                "LineItemGroups": [],
            }
        ],
        "ResponseMetadata": {
            "RequestId": "expense-1",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
            "RetryAttempts": 0,
        },
    }
