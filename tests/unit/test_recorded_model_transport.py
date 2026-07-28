import pytest

from claims_backend.domain.extraction import ComplexExtractionOutput, ModelRoute
from claims_backend.infrastructure.fixtures.recorded_model import (
    RecordedStructuredModelTransport,
)
from claims_backend.model.routing import ModelRouter


def test_recorded_transport_replays_route_responses_in_order() -> None:
    transport = RecordedStructuredModelTransport(
        {
            ModelRoute.COMPLEX_EXTRACTION: (
                {"schema_version": "complex-extraction-v1", "candidates": []},
                {
                    "schema_version": "complex-extraction-v1",
                    "candidates": [{"document": "second"}],
                },
            )
        }
    )
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)

    first = transport.invoke(config, ComplexExtractionOutput, [])
    second = transport.invoke(config, ComplexExtractionOutput, [])

    assert first.raw_output["candidates"] == []
    assert second.raw_output["candidates"] == [{"document": "second"}]
    with pytest.raises(RuntimeError, match="No recorded response remains"):
        transport.invoke(config, ComplexExtractionOutput, [])
