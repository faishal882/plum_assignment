import pytest

from claims_backend.domain.evidence import NormalizedRegion
from claims_backend.domain.extraction import (
    ModelAuthorityViolation,
    ModelGroundingValidationError,
    ModelRoute,
    ModelSchemaValidationError,
    ModelSemanticValidationError,
)
from claims_backend.domain.ocr import OcrObservation, OcrObservationKind
from claims_backend.domain.workflow import ExecutionContract
from claims_backend.model.application import (
    COMPLEX_EXTRACTION_SYSTEM_PROMPT,
    COMPLEX_EXTRACTION_SYSTEM_PROMPT_V3,
    _merge_textract_derived_candidates,
    complex_extraction_system_prompt,
)
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
    assert complex_route.prompt_version == "complex-extraction-prompt-v4"
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
    assert "field_type is TOTAL" in COMPLEX_EXTRACTION_SYSTEM_PROMPT


def test_router_rebuilds_a_supported_historical_contract_and_prompt() -> None:
    contract = ExecutionContract(
        schema_version="execution-contract-v1",
        execution_profile="RECORDED_LOCAL",
        ocr_provider_name="RECORDED_DISCOVERY_OCR",
        ocr_provider_version="recorded-discovery-v1",
        model_provider_name="RECORDED_DOCUMENT_MODEL",
        model_provider_version="recorded-document-v1",
        model_routes=(
            (
                "FAST_TRIAGE",
                "qwen.qwen3-235b-a22b-2507-v1:0",
                "us-west-2",
                "fast-triage-prompt-v2",
                "triage-output-v3",
            ),
            (
                "COMPLEX_EXTRACTION",
                "qwen.qwen3-235b-a22b-2507-v1:0",
                "us-west-2",
                "complex-extraction-prompt-v3",
                "complex-extraction-v1",
            ),
        ),
    )

    config = ModelRouter.from_execution_contract(contract).resolve(ModelRoute.COMPLEX_EXTRACTION)

    assert config.prompt_version == "complex-extraction-prompt-v3"
    assert complex_extraction_system_prompt(config) == COMPLEX_EXTRACTION_SYSTEM_PROMPT_V3


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
    assert first[0].producer_version.endswith("complex-extraction-prompt-v4")
    assert first[0].candidate_schema_version == "complex-extraction-v1"
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


def test_provider_labelled_textract_total_is_a_grounded_fallback_candidate() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    observation = OcrObservation(
        observation_id="a" * 64,
        document_version_id="00000000-0000-0000-0000-000000000001",
        page_number=1,
        kind=OcrObservationKind.EXPENSE_FIELD,
        text="₹ 1,500.00",
        confidence=0.99,
        region=NormalizedRegion(x=0, y=0, width=1, height=1),
        source_id="expense:0:summary:0",
        field_type="TOTAL",
    )

    candidates = _merge_textract_derived_candidates((), (observation,), config)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.fact_path == "billing.total"
    assert candidate.value == candidate.normalized_value == "1500.00"
    assert candidate.evidence_refs == (observation.observation_id,)
    assert candidate.producer == "TEXTRACT_DERIVED"
    assert candidate.producer_version == "boto3-textract-v1:expense-total-v1"
    assert candidate.candidate_schema_version == "textract-expense-total-v1"


def test_textract_total_fallback_rejects_unlabelled_or_non_currency_text() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    base = {
        "observation_id": "b" * 64,
        "document_version_id": "00000000-0000-0000-0000-000000000001",
        "page_number": 1,
        "kind": OcrObservationKind.EXPENSE_FIELD,
        "confidence": 0.99,
        "region": NormalizedRegion(x=0, y=0, width=1, height=1),
        "source_id": "expense:0:summary:0",
    }
    unlabelled = OcrObservation(text="1500.00", **base)
    prose = OcrObservation(text="Total 1500", field_type="TOTAL", **base)

    assert _merge_textract_derived_candidates((), (unlabelled,), config) == ()
    assert _merge_textract_derived_candidates((), (prose,), config) == ()


def test_textract_total_fallback_is_not_suppressed_by_an_unusable_model_value() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    observation = OcrObservation(
        observation_id="c" * 64,
        document_version_id="00000000-0000-0000-0000-000000000001",
        page_number=1,
        kind=OcrObservationKind.EXPENSE_FIELD,
        text="1500",
        confidence=0.99,
        region=NormalizedRegion(x=0, y=0, width=1, height=1),
        source_id="expense:0:summary:0",
        field_type="TOTAL",
    )
    unusable_model = validate_complex_output(
        {
            "schema_version": "complex-extraction-v1",
            "candidates": [
                {
                    "fact_path": "billing.total",
                    "value": None,
                    "normalized_value": None,
                    "evidence_refs": [observation.observation_id],
                    "confidence": 0.6,
                }
            ],
        },
        config,
        available_observation_ids={observation.observation_id},
    )

    candidates = _merge_textract_derived_candidates(unusable_model, (observation,), config)

    assert len(candidates) == 2
    assert candidates[-1].producer == "TEXTRACT_DERIVED"
    assert candidates[-1].normalized_value == "1500.00"


def test_textract_diagnosis_line_is_a_grounded_fallback_candidate() -> None:
    config = ModelRouter.default(
        region="us-west-2",
        model_id="qwen.qwen3-235b-a22b-2507-v1:0",
    ).resolve(ModelRoute.COMPLEX_EXTRACTION)
    observation = OcrObservation(
        observation_id="d" * 64,
        document_version_id="00000000-0000-0000-0000-000000000001",
        page_number=1,
        kind=OcrObservationKind.LINE,
        text="Diagnosis: Viral Fever",
        confidence=0.99,
        region=NormalizedRegion(x=0, y=0, width=1, height=1),
        source_id="line-1",
    )

    candidates = _merge_textract_derived_candidates((), (observation,), config)

    assert len(candidates) == 1
    assert candidates[0].fact_path == "clinical.condition"
    assert candidates[0].normalized_value == "Viral Fever"
    assert candidates[0].producer_version == "boto3-textract-v1:diagnosis-line-v1"


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
