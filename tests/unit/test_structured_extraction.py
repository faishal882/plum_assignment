import pytest

from claims_backend.domain.extraction import (
    ModelAuthorityViolation,
    ModelGroundingValidationError,
    ModelRoute,
    ModelSchemaValidationError,
    ModelSemanticValidationError,
)
from claims_backend.model.application import COMPLEX_EXTRACTION_SYSTEM_PROMPT
from claims_backend.model.extraction import validate_complex_output
from claims_backend.model.routing import ModelRouter


def test_fast_and_complex_routes_are_independently_versioned_and_approved() -> None:
    router = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    )

    fast = router.resolve(ModelRoute.FAST_TRIAGE)
    complex_route = router.resolve(ModelRoute.COMPLEX_EXTRACTION)

    assert fast.route is ModelRoute.FAST_TRIAGE
    assert complex_route.route is ModelRoute.COMPLEX_EXTRACTION
    assert fast.model_id == complex_route.model_id == "qwen.qwen3-235b-a22b-2507-v1:0"
    assert fast.prompt_version != complex_route.prompt_version
    assert complex_route.prompt_version == "complex-extraction-prompt-v3"
    assert fast.schema_version != complex_route.schema_version
    assert fast.enabled and fast.evaluation_approved
    assert complex_route.enabled and complex_route.evaluation_approved
    assert fast.temperature == complex_route.temperature == 0
    assert (
        fast.structured_output_method
        == complex_route.structured_output_method
        == "function_calling"
    )
    assert "clinical.condition for a diagnosis or condition" in COMPLEX_EXTRACTION_SYSTEM_PROMPT
    assert "Do not use clinical.diagnosis" in COMPLEX_EXTRACTION_SYSTEM_PROMPT


def test_authority_bearing_model_output_is_rejected_before_schema_parsing() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    raw = _valid_output()
    raw["decision"] = "APPROVED"

    with pytest.raises(ModelAuthorityViolation) as captured:
        validate_complex_output(raw, config, available_observation_ids={"ocr-1"})

    assert captured.value.code == "MODEL_AUTHORITY_VIOLATION"


def test_schema_semantic_and_grounding_failures_remain_distinct() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)

    schema_failure = _valid_output()
    schema_failure["unexpected"] = True
    with pytest.raises(ModelSchemaValidationError) as schema:
        validate_complex_output(
            schema_failure,
            config,
            available_observation_ids={"ocr-1"},
        )

    semantic_failure = _valid_output()
    semantic_failure["candidates"][0]["fact_path"] = "unsupported.result"
    with pytest.raises(ModelSemanticValidationError) as semantic:
        validate_complex_output(
            semantic_failure,
            config,
            available_observation_ids={"ocr-1"},
        )

    with pytest.raises(ModelGroundingValidationError) as grounding:
        validate_complex_output(
            _valid_output(),
            config,
            available_observation_ids={"different-observation"},
        )

    assert schema.value.code == "MODEL_SCHEMA_VALIDATION_FAILED"
    assert semantic.value.code == "MODEL_SEMANTIC_VALIDATION_FAILED"
    assert grounding.value.code == "MODEL_GROUNDING_VALIDATION_FAILED"


def test_valid_candidates_are_grounded_and_canonically_identified() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)

    first = validate_complex_output(
        _valid_output(),
        config,
        available_observation_ids={"ocr-1"},
    )
    replay = validate_complex_output(
        _valid_output(),
        config,
        available_observation_ids={"ocr-1"},
    )

    assert replay == first
    assert first[0].evidence_refs == ("ocr-1",)
    assert first[0].producer == "BEDROCK"
    assert first[0].candidate_id


def test_versioned_diagnosis_alias_preserves_source_path_and_registry_provenance() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    raw = _valid_output()
    raw["candidates"][0]["fact_path"] = "clinical.diagnosis"  # type: ignore[index]

    candidate = validate_complex_output(
        raw,
        config,
        available_observation_ids={"ocr-1"},
    )[0]

    assert candidate.fact_path == "clinical.condition"
    assert candidate.source_fact_path == "clinical.diagnosis"
    assert candidate.alias_registry_version == "fact-path-aliases-v1"
    assert candidate.evidence_refs == ("ocr-1",)


def _valid_output() -> dict[str, object]:
    return {
        "schema_version": "complex-extraction-v1",
        "candidates": [
            {
                "fact_path": "billing.total",
                "value": "800.00",
                "normalized_value": "800.00",
                "evidence_refs": ["ocr-1"],
                "confidence": 0.98,
            }
        ],
    }
