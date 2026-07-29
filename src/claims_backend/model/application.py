import asyncio
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from claims_backend.domain.evidence import TriageModelOutput, TriageProviderOutputV4
from claims_backend.domain.extraction import (
    ComplexExtractionOutput,
    EvidenceCandidate,
    ModelRoute,
    ModelSchemaValidationError,
)
from claims_backend.domain.ocr import OcrObservation
from claims_backend.model.extraction import (
    reject_authority_fields,
    validate_complex_output,
)
from claims_backend.model.routing import ModelRouteConfig, ModelRouter
from claims_backend.model.transport import ModelInvocation, StructuredModelTransport

FAST_TRIAGE_SYSTEM_PROMPT_V2 = (
    "Classify each submitted claim document from discovery OCR. Return semantic predictions only: "
    "document role, readability status, and patient-name values. Ground every prediction by "
    "copying the exact supplied observation_id values into the corresponding evidence-reference "
    "fields. "
    "Treat observation IDs as opaque references: never create, alter, or infer an ID. Never return "
    "hashes, page numbers, regions, document version IDs, render metadata, OCR confidence, policy "
    "decisions, or payment recommendations."
)
FAST_TRIAGE_SYSTEM_PROMPT_V3 = (
    "Classify each submitted claim document from discovery OCR. Return semantic predictions only: "
    "document role, readability status, and patient-name values. Ground every prediction by "
    "copying the exact supplied observation_id values into the corresponding evidence-reference "
    "fields. For role_evidence_refs and readability_evidence_refs, return 1–5 direct "
    "observation IDs only, ordered strongest to weakest. Prefer document titles, patient lines, "
    "bill or receipt lines, prescription lines, and total amount lines. Do not cite every OCR "
    "line. Treat observation IDs as opaque references: never create, alter, or infer an ID. "
    "Never return hashes, page numbers, regions, document version IDs, render metadata, OCR "
    "confidence, policy decisions, or payment recommendations."
)
FAST_TRIAGE_SYSTEM_PROMPT = FAST_TRIAGE_SYSTEM_PROMPT_V3
COMPLEX_EXTRACTION_SYSTEM_PROMPT_V3 = (
    "Extract grounded evidence candidates only. Never decide policy or payment. "
    "Every fact_path must begin with exactly one allowed namespace: billing., "
    "clinical., document., patient., provider., or treatment. Use billing.total for "
    "a bill's total amount and provider.name for the treating hospital or provider. "
    "Every candidate must cite one or more supplied observation_id values."
)
COMPLEX_EXTRACTION_SYSTEM_PROMPT = (
    "Extract grounded evidence candidates only. Never decide policy or payment. "
    "Every fact_path must begin with exactly one allowed namespace: billing., "
    "clinical., document., patient., provider., or treatment. Use billing.total for "
    "a bill's total amount, clinical.condition for a diagnosis or condition, and "
    "provider.name for the treating hospital or provider. Do not use clinical.diagnosis. "
    "For an EXPENSE_FIELD whose field_type is TOTAL, emit exactly one billing.total "
    "candidate grounded to that observation unless its value is unreadable. "
    "Every candidate must cite one or more supplied observation_id values."
)


def complex_extraction_system_prompt(config: ModelRouteConfig) -> str:
    if config.prompt_version == "complex-extraction-prompt-v3":
        return COMPLEX_EXTRACTION_SYSTEM_PROMPT_V3
    if config.prompt_version == "complex-extraction-prompt-v4":
        return COMPLEX_EXTRACTION_SYSTEM_PROMPT
    raise ModelSchemaValidationError("Persisted complex extraction prompt is unsupported.")


@dataclass(frozen=True, slots=True)
class FastTriageResult:
    config: ModelRouteConfig
    invocation: ModelInvocation
    output: TriageModelOutput | TriageProviderOutputV4
    raw_output_sha256: str


@dataclass(frozen=True, slots=True)
class ComplexExtractionResult:
    document_version_id: UUID
    input_sha256: str
    config: ModelRouteConfig
    invocation: ModelInvocation
    candidates: tuple[EvidenceCandidate, ...]


class StructuredModelRepository(Protocol):
    async def find(
        self,
        document_version_id: UUID,
        config: ModelRouteConfig,
        input_sha256: str,
    ) -> ComplexExtractionResult | None: ...

    async def save(
        self,
        result: ComplexExtractionResult,
    ) -> ComplexExtractionResult: ...


class StructuredModelApplication:
    def __init__(
        self,
        router: ModelRouter,
        transport: StructuredModelTransport,
        repository: StructuredModelRepository,
    ) -> None:
        self._router = router
        self._transport = transport
        self._repository = repository

    async def fast_triage(
        self,
        messages: list[tuple[str, str]],
    ) -> FastTriageResult:
        config = self._router.resolve(ModelRoute.FAST_TRIAGE)
        schema = triage_output_schema(config)
        invocation = await asyncio.to_thread(
            self._transport.invoke,
            config,
            schema,
            messages,
        )
        reject_authority_fields(invocation.raw_output)
        try:
            output = schema.model_validate(invocation.raw_output)
        except ValidationError as error:
            raise ModelSchemaValidationError("Model output failed the triage schema.") from error
        return FastTriageResult(
            config=config,
            invocation=invocation,
            output=output,
            raw_output_sha256=sha256(
                json.dumps(
                    invocation.raw_output,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        )

    async def extract_complex(
        self,
        document_version_id: UUID,
        observations: tuple[OcrObservation, ...],
    ) -> ComplexExtractionResult:
        config = self._router.resolve(ModelRoute.COMPLEX_EXTRACTION)
        bounded = observations[:500]
        input_sha256 = _input_sha256(config, bounded)
        stored = await self._repository.find(
            document_version_id,
            config,
            input_sha256,
        )
        if stored is not None:
            return stored
        messages = [
            (
                "system",
                complex_extraction_system_prompt(config),
            ),
            (
                "human",
                json.dumps(
                    {
                        "schema_version": config.schema_version,
                        "ocr_observations": [
                            observation.model_dump(mode="json") for observation in bounded
                        ],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ]
        invocation = await asyncio.to_thread(
            self._transport.invoke,
            config,
            ComplexExtractionOutput,
            messages,
        )
        candidates = validate_complex_output(
            invocation.raw_output,
            config,
            available_observation_ids={observation.observation_id for observation in bounded},
        )
        candidates = _merge_textract_derived_candidates(candidates, bounded, config)
        return await self._repository.save(
            ComplexExtractionResult(
                document_version_id=document_version_id,
                input_sha256=input_sha256,
                config=config,
                invocation=invocation,
                candidates=candidates,
            )
        )


def triage_output_schema(
    config: ModelRouteConfig,
) -> type[TriageModelOutput] | type[TriageProviderOutputV4]:
    if (
        config.prompt_version == "fast-triage-prompt-v2"
        and config.schema_version == "triage-output-v3"
    ):
        return TriageModelOutput
    if (
        config.prompt_version == "fast-triage-prompt-v3"
        and config.schema_version == "triage-provider-output-v4"
    ):
        return TriageProviderOutputV4
    raise ModelSchemaValidationError("Persisted fast triage route is unsupported.")


def fast_triage_system_prompt(config: ModelRouteConfig) -> str:
    if config.prompt_version == "fast-triage-prompt-v2":
        return FAST_TRIAGE_SYSTEM_PROMPT_V2
    if config.prompt_version == "fast-triage-prompt-v3":
        return FAST_TRIAGE_SYSTEM_PROMPT_V3
    raise ModelSchemaValidationError("Persisted fast triage prompt is unsupported.")


def _input_sha256(
    config: ModelRouteConfig,
    observations: tuple[OcrObservation, ...],
) -> str:
    canonical = json.dumps(
        {
            "model_id": config.model_id,
            "route": config.route.value,
            "prompt_version": config.prompt_version,
            "schema_version": config.schema_version,
            "structured_output_method": config.structured_output_method,
            "observations": [observation.model_dump(mode="json") for observation in observations],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(canonical).hexdigest()


def _merge_textract_derived_candidates(
    model_candidates: tuple[EvidenceCandidate, ...],
    observations: tuple[OcrObservation, ...],
    config: ModelRouteConfig,
) -> tuple[EvidenceCandidate, ...]:
    """Add only exact, provider-labelled facts omitted or left blank by the model."""
    derived: list[EvidenceCandidate] = []
    for observation in observations:
        if observation.kind.value == "EXPENSE_FIELD" and observation.field_type == "TOTAL":
            amount = _canonical_currency_amount(observation.text)
            if amount is not None:
                derived.append(
                    _textract_candidate(
                        fact_path="billing.total",
                        value=amount,
                        observation=observation,
                        config=config,
                        decoder_version="expense-total-v1",
                        semantic_label=observation.field_type,
                    )
                )
        condition = _diagnosis_line_value(observation.text)
        if observation.kind.value == "LINE" and condition is not None:
            derived.append(
                _textract_candidate(
                    fact_path="clinical.condition",
                    value=condition,
                    observation=observation,
                    config=config,
                    decoder_version="diagnosis-line-v1",
                    semantic_label="DIAGNOSIS",
                )
            )
    return (*model_candidates, *derived)


def _textract_candidate(
    *,
    fact_path: str,
    value: str,
    observation: OcrObservation,
    config: ModelRouteConfig,
    decoder_version: str,
    semantic_label: str,
) -> EvidenceCandidate:
    candidate_schema_version = f"textract-{decoder_version}"
    producer_version = f"boto3-textract-v1:{decoder_version}"
    canonical = json.dumps(
        {
            "fact_path": fact_path,
            "source_fact_path": fact_path,
            "value": value,
            "normalized_value": value,
            "evidence_refs": [observation.observation_id],
            "producer": "TEXTRACT_DERIVED",
            "producer_version": producer_version,
            "candidate_schema_version": candidate_schema_version,
            "source_semantic_label": semantic_label,
            "model_route": config.route.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return EvidenceCandidate(
        candidate_id=sha256(canonical).hexdigest(),
        fact_path=fact_path,
        source_fact_path=fact_path,
        value=value,
        normalized_value=value,
        evidence_refs=(observation.observation_id,),
        confidence=observation.confidence,
        producer="TEXTRACT_DERIVED",
        producer_version=producer_version,
        candidate_schema_version=candidate_schema_version,
        model_id=config.model_id,
        route=config.route,
        prompt_version=config.prompt_version,
        schema_version=config.schema_version,
    )


def _canonical_currency_amount(value: str) -> str | None:
    """Parse a standalone Indian-currency amount without inferring values from prose."""
    cleaned = value.strip().replace(",", "")
    for prefix in ("₹", "INR", "Rs.", "Rs", "rs.", "rs"):
        if cleaned.startswith(prefix):
            cleaned = cleaned.removeprefix(prefix).strip()
            break
    if not cleaned or any(character not in "0123456789." for character in cleaned):
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        return None
    return f"{amount:.2f}"


_DIAGNOSIS_LINE = re.compile(r"^diagnos(?:is|es)\s*[:\-]\s*(?P<value>.+)$", re.IGNORECASE)


def _diagnosis_line_value(value: str) -> str | None:
    match = _DIAGNOSIS_LINE.match(value.strip())
    if match is None:
        return None
    condition = match.group("value").strip()
    return condition or None
