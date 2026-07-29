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
    "provider.",
    "treatment.",
)
_FACT_PATH_ALIAS_REGISTRY_VERSION = "fact-path-aliases-v1"
_FACT_PATH_ALIASES = {
    "clinical.diagnosis": (
        "clinical.condition",
        frozenset({"complex-extraction-v1"}),
    ),
}


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
    normalized_raw, source_paths, alias_versions = _normalize_fact_path_aliases(raw, config)
    try:
        output = ComplexExtractionOutput.model_validate(normalized_raw)
    except ValidationError as error:
        raise ModelSchemaValidationError("Model output failed the extraction schema.") from error
    candidates: list[EvidenceCandidate] = []
    for candidate, source_path, alias_version in zip(
        output.candidates,
        source_paths,
        alias_versions,
        strict=True,
    ):
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
                "source_fact_path": source_path,
                "alias_registry_version": alias_version,
                "model_id": config.model_id,
                "route": config.route.value,
                "prompt_version": config.prompt_version,
                "schema_version": config.schema_version,
                "structured_output_method": config.structured_output_method,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        candidates.append(
            EvidenceCandidate(
                candidate_id=sha256(canonical).hexdigest(),
                fact_path=candidate.fact_path,
                source_fact_path=source_path,
                alias_registry_version=alias_version,
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


def _normalize_fact_path_aliases(
    raw: Mapping[str, object],
    config: ModelRouteConfig,
) -> tuple[dict[str, object], tuple[str, ...], tuple[str | None, ...]]:
    """Normalize only explicitly-versioned model aliases before schema validation.

    The original path and registry version become immutable candidate provenance;
    callers cannot supply those fields themselves.
    """
    normalized = dict(raw)
    raw_candidates = raw.get("candidates")
    if not isinstance(raw_candidates, list):
        return normalized, (), ()
    candidates: list[object] = []
    source_paths: list[str] = []
    alias_versions: list[str | None] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, Mapping):
            candidates.append(raw_candidate)
            continue
        candidate = dict(raw_candidate)
        fact_path = candidate.get("fact_path")
        if not isinstance(fact_path, str):
            candidates.append(candidate)
            continue
        source_paths.append(fact_path)
        alias = _FACT_PATH_ALIASES.get(fact_path)
        if alias is None:
            alias_versions.append(None)
        else:
            target_path, schema_versions = alias
            if config.schema_version not in schema_versions:
                raise ModelSemanticValidationError(
                    f"Fact-path alias {fact_path} is not enabled for {config.schema_version}."
                )
            candidate["fact_path"] = target_path
            alias_versions.append(_FACT_PATH_ALIAS_REGISTRY_VERSION)
        candidates.append(candidate)
    normalized["candidates"] = candidates
    return normalized, tuple(source_paths), tuple(alias_versions)


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
