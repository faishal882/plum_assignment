from unittest.mock import patch
from uuid import UUID

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ReadTimeoutError
from botocore.stub import Stubber

from claims_backend.application.intelligence import RenderedPage
from claims_backend.domain.evidence import DocumentRole
from claims_backend.domain.ocr import (
    OcrMalformedResponseError,
    OcrProviderError,
    OcrThrottledError,
    OcrTimeoutError,
    TextractProfile,
)
from claims_backend.infrastructure.aws.textract import TextractAdapter


def test_textract_profiles_send_page_bytes_and_map_project_observations() -> None:
    client = _client()
    adapter = TextractAdapter(client)
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
