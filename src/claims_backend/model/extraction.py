import json
from collections.abc import Mapping
from hashlib import sha256

from pydantic import ValidationError

from claims_backend.domain.extraction import (
    ComplexExtractionOutput,
    EvidenceCandidate,
    ModelAuthorityViolation,
    ModelGroundingValidationError,
    ModelRoute,
    ModelSchemaValidationError,
    ModelSemanticValidationError,
)
from claims_backend.model.routing import ModelRouteConfig

_AUTHORITY_FIELDS = {
    "approved_amount",
    "approved_paise",
    "decision",
    "payable_amount",
    "policy_outcome",
    "policy_result",
    "reason_code",
    "recommendation",
}
_ALLOWED_FACT_PREFIXES = (
    "billing.",
    "clinical.",
    "document.",
    "patient.",
    "treatment.",
)


def validate_complex_output(
    raw: Mapping[str, object],
    config: ModelRouteConfig,
    *,
    available_observation_ids: set[str],
) -> tuple[EvidenceCandidate, ...]:
    if config.route is not ModelRoute.COMPLEX_EXTRACTION:
        raise ModelSemanticValidationError(
            "Complex extraction output used with the wrong model route."
        )
    reject_authority_fields(raw)
    try:
        output = ComplexExtractionOutput.model_validate(raw)
    except ValidationError as error:
        raise ModelSchemaValidationError("Model output failed the extraction schema.") from error
    candidates: list[EvidenceCandidate] = []
    for candidate in output.candidates:
        if not candidate.fact_path.startswith(_ALLOWED_FACT_PREFIXES):
            raise ModelSemanticValidationError(
                f"Unsupported evidence fact path: {candidate.fact_path}."
            )
        missing = set(candidate.evidence_refs) - available_observation_ids
        if missing:
            raise ModelGroundingValidationError(
                "Model candidate references unavailable OCR observations."
            )
        canonical = json.dumps(
            {
                "candidate": candidate.model_dump(mode="json"),
                "model_id": config.model_id,
                "route": config.route.value,
                "prompt_version": config.prompt_version,
                "schema_version": config.schema_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        candidates.append(
            EvidenceCandidate(
                candidate_id=sha256(canonical).hexdigest(),
                fact_path=candidate.fact_path,
                value=candidate.value,
                normalized_value=candidate.normalized_value,
                evidence_refs=candidate.evidence_refs,
                confidence=candidate.confidence,
                model_id=config.model_id,
                route=config.route,
                prompt_version=config.prompt_version,
                schema_version=config.schema_version,
            )
        )
    return tuple(candidates)


def reject_authority_fields(raw: Mapping[str, object]) -> None:
    forbidden = _find_authority_fields(raw)
    if forbidden:
        raise ModelAuthorityViolation(
            f"Model output crossed the financial authority boundary: {forbidden[0]}."
        )


def _find_authority_fields(value: object, path: str = "") -> list[str]:
    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text.casefold() in _AUTHORITY_FIELDS:
                matches.append(child_path)
            matches.extend(_find_authority_fields(item, child_path))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            matches.extend(_find_authority_fields(item, f"{path}[{index}]"))
    return sorted(matches)
