from os import environ

import pytest

from claims_backend.domain.extraction import (
    ComplexExtractionOutput,
    ModelRoute,
)
from claims_backend.infrastructure.aws.bedrock import ChatBedrockConverseTransport
from claims_backend.model.extraction import validate_complex_output
from claims_backend.model.routing import ModelRouter

pytestmark = [
    pytest.mark.live_aws,
    pytest.mark.skipif(
        environ.get("CLAIMS_RUN_LIVE_AWS") != "1",
        reason="Set CLAIMS_RUN_LIVE_AWS=1 to permit the synthetic AWS smoke test.",
    ),
]


def test_synthetic_ocr_passes_live_bedrock_structured_output_smoke() -> None:
    config = ModelRouter.default(
        region=environ.get("CLAIMS_AWS_REGION", "us-east-1"),
        model_id=environ.get(
            "CLAIMS_BEDROCK_MODEL_ID",
            "us.anthropic.claude-sonnet-4-6",
        ),
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    invocation = ChatBedrockConverseTransport().invoke(
        config,
        ComplexExtractionOutput,
        [
            (
                "system",
                "Extract grounded evidence only. Never decide policy or payment.",
            ),
            (
                "human",
                (
                    "Synthetic OCR observation ID ocr-live-1: "
                    "hospital bill total INR 800.00. Return schema version "
                    "complex-extraction-v1 and cite ocr-live-1."
                ),
            ),
        ],
    )
    candidates = validate_complex_output(
        invocation.raw_output,
        config,
        available_observation_ids={"ocr-live-1"},
    )

    assert invocation.provider_request_id
    assert invocation.latency_ms > 0
    assert invocation.input_tokens > 0
    assert invocation.output_tokens > 0
    assert invocation.stop_reason
    assert candidates
    assert all("ocr-live-1" in candidate.evidence_refs for candidate in candidates)
