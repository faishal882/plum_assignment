import asyncio
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from claims_backend.domain.evidence import TriageModelOutput
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

COMPLEX_EXTRACTION_SYSTEM_PROMPT = (
    "Extract grounded evidence candidates only. Never decide policy or payment. "
    "Every fact_path must begin with exactly one allowed namespace: billing., "
    "clinical., document., patient., provider., or treatment. Use billing.total for "
    "a bill's total amount, clinical.condition for a diagnosis or condition, and "
    "provider.name for the treating hospital or provider. Do not use clinical.diagnosis. "
    "Every candidate must cite one or more supplied observation_id values."
)


@dataclass(frozen=True, slots=True)
class FastTriageResult:
    config: ModelRouteConfig
    invocation: ModelInvocation
    output: TriageModelOutput


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
        invocation = await asyncio.to_thread(
            self._transport.invoke,
            config,
            TriageModelOutput,
            messages,
        )
        reject_authority_fields(invocation.raw_output)
        try:
            output = TriageModelOutput.model_validate(invocation.raw_output)
        except ValidationError as error:
            raise ModelSchemaValidationError("Model output failed the triage schema.") from error
        return FastTriageResult(config=config, invocation=invocation, output=output)

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
                COMPLEX_EXTRACTION_SYSTEM_PROMPT,
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
        return await self._repository.save(
            ComplexExtractionResult(
                document_version_id=document_version_id,
                input_sha256=input_sha256,
                config=config,
                invocation=invocation,
                candidates=candidates,
            )
        )


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
