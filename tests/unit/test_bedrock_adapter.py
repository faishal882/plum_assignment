from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ReadTimeoutError
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from claims_backend.domain.extraction import (
    ComplexExtractionOutput,
    ModelProviderError,
    ModelRoute,
)
from claims_backend.infrastructure.aws.bedrock import ChatBedrockConverseTransport
from claims_backend.model.routing import ModelRouter
from claims_backend.observability import ObservabilityConfig, create_observability


def test_bedrock_transport_uses_pinned_model_and_compatible_structured_output(
    tmp_path: Path,
) -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    parsed = ComplexExtractionOutput.model_validate(
        {
            "schema_version": "complex-extraction-v1",
            "candidates": [],
        }
    )
    raw_message = Mock(
        response_metadata={
            "ResponseMetadata": {"RequestId": "bedrock-request-1"},
            "stopReason": "end_turn",
        },
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 8,
            "total_tokens": 20,
        },
    )
    runnable = Mock()
    runnable.invoke.return_value = {
        "parsed": parsed,
        "raw": raw_message,
        "parsing_error": None,
    }
    model = Mock()
    model.with_structured_output.return_value = runnable
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=exporter,
    )

    with patch(
        "claims_backend.infrastructure.aws.bedrock.ChatBedrockConverse",
        return_value=model,
    ) as constructor:
        result = ChatBedrockConverseTransport(
            read_timeout_seconds=91,
            observability=observability,
        ).invoke(
            config,
            ComplexExtractionOutput,
            [
                ("system", "Extract grounded evidence only."),
                ("human", "Synthetic OCR observation."),
            ],
        )

    constructor.assert_called_once()
    assert constructor.call_args.kwargs["model"] == "qwen.qwen3-235b-a22b-2507-v1:0"
    assert constructor.call_args.kwargs["region_name"] == "us-west-2"
    assert constructor.call_args.kwargs["temperature"] == 0
    provider_config = constructor.call_args.kwargs["config"]
    assert provider_config.read_timeout == 91
    assert provider_config.retries["total_max_attempts"] == 1
    model.with_structured_output.assert_called_once_with(
        ComplexExtractionOutput,
        method="function_calling",
        include_raw=True,
    )
    assert result.raw_output == {
        "schema_version": "complex-extraction-v1",
        "candidates": [],
    }
    assert result.provider_request_id == "bedrock-request-1"
    assert result.input_tokens == 12
    assert result.output_tokens == 8
    assert result.stop_reason == "end_turn"
    assert result.latency_ms >= 0
    observability.shutdown()
    span = exporter.get_finished_spans()[0]
    assert span.name == "bedrock.converse"
    assert span.attributes["model.route"] == "COMPLEX_EXTRACTION"
    assert span.attributes["model.id"] == "qwen.qwen3-235b-a22b-2507-v1:0"
    assert span.attributes["model.prompt_version"] == "complex-extraction-prompt-v3"
    assert span.attributes["model.schema_version"] == "complex-extraction-v1"
    assert span.attributes["llm.token_count.prompt"] == 12
    assert span.attributes["llm.token_count.completion"] == 8
    assert span.attributes["provider.request_id"] == "bedrock-request-1"
    assert "input.value" not in span.attributes
    assert "output.value" not in span.attributes


def test_bedrock_transport_bounds_concurrent_provider_calls() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    parsed = ComplexExtractionOutput.model_validate(
        {"schema_version": "complex-extraction-v1", "candidates": []}
    )
    release = Event()
    two_started = Event()
    lock = Lock()
    active = 0
    maximum_active = 0

    def invoke(_: object) -> dict[str, object]:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                two_started.set()
        assert release.wait(timeout=2)
        with lock:
            active -= 1
        return {
            "parsed": parsed,
            "raw": Mock(
                response_metadata={"ResponseMetadata": {"RequestId": "request-1"}},
                usage_metadata={"input_tokens": 1, "output_tokens": 1},
            ),
            "parsing_error": None,
        }

    runnable = Mock()
    runnable.invoke.side_effect = invoke
    model = Mock()
    model.with_structured_output.return_value = runnable
    transport = ChatBedrockConverseTransport(concurrency_limit=2)

    with (
        patch(
            "claims_backend.infrastructure.aws.bedrock.ChatBedrockConverse",
            return_value=model,
        ),
        ThreadPoolExecutor(max_workers=3) as pool,
    ):
        futures = [
            pool.submit(
                transport.invoke,
                config,
                ComplexExtractionOutput,
                [("human", "synthetic")],
            )
            for _ in range(3)
        ]
        assert two_started.wait(timeout=2)
        assert maximum_active == 2
        release.set()
        for future in futures:
            future.result(timeout=2)

    assert maximum_active == 2


def test_bedrock_timeout_has_a_retryable_typed_failure() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    runnable = Mock()
    runnable.invoke.side_effect = ReadTimeoutError(
        endpoint_url="https://bedrock-runtime.us-west-2.amazonaws.com"
    )
    model = Mock()
    model.with_structured_output.return_value = runnable

    with (
        patch(
            "claims_backend.infrastructure.aws.bedrock.ChatBedrockConverse",
            return_value=model,
        ),
        pytest.raises(ModelProviderError) as captured,
    ):
        ChatBedrockConverseTransport().invoke(
            config,
            ComplexExtractionOutput,
            [("human", "synthetic")],
        )

    assert captured.value.code == "BEDROCK_TIMEOUT"
    assert captured.value.retryable is True
