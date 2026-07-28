from unittest.mock import Mock, patch

from claims_backend.domain.extraction import (
    ComplexExtractionOutput,
    ModelRoute,
)
from claims_backend.infrastructure.aws.bedrock import ChatBedrockConverseTransport
from claims_backend.model.routing import ModelRouter


def test_bedrock_transport_uses_pinned_model_and_compatible_structured_output() -> None:
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

    with patch(
        "claims_backend.infrastructure.aws.bedrock.ChatBedrockConverse",
        return_value=model,
    ) as constructor:
        result = ChatBedrockConverseTransport().invoke(
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
