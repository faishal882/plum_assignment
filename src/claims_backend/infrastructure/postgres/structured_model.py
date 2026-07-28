from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.domain.extraction import EvidenceCandidate, ModelRoute
from claims_backend.infrastructure.postgres.models import (
    EvidenceCandidateRow,
    ModelExtractionRow,
)
from claims_backend.model.application import ComplexExtractionResult
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation


class PostgresStructuredModelRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find(
        self,
        document_version_id: UUID,
        config: ModelRouteConfig,
        input_sha256: str,
    ) -> ComplexExtractionResult | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ModelExtractionRow).where(
                    ModelExtractionRow.document_version_id == document_version_id,
                    ModelExtractionRow.route == config.route.value,
                    ModelExtractionRow.model_id == config.model_id,
                    ModelExtractionRow.prompt_version == config.prompt_version,
                    ModelExtractionRow.schema_version == config.schema_version,
                    ModelExtractionRow.input_sha256 == input_sha256,
                )
            )
            if row is None:
                return None
            candidates = (
                await session.scalars(
                    select(EvidenceCandidateRow)
                    .where(EvidenceCandidateRow.model_extraction_id == row.id)
                    .order_by(EvidenceCandidateRow.candidate_id)
                )
            ).all()
        return _to_result(row, candidates)

    async def save(
        self,
        result: ComplexExtractionResult,
    ) -> ComplexExtractionResult:
        extraction_id = uuid4()
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ModelExtractionRow)
                .values(
                    id=extraction_id,
                    document_version_id=result.document_version_id,
                    route=result.config.route.value,
                    model_id=result.config.model_id,
                    region=result.config.region,
                    prompt_version=result.config.prompt_version,
                    schema_version=result.config.schema_version,
                    input_sha256=result.input_sha256,
                    provider_request_id=result.invocation.provider_request_id,
                    input_tokens=result.invocation.input_tokens,
                    output_tokens=result.invocation.output_tokens,
                    latency_ms=result.invocation.latency_ms,
                    stop_reason=result.invocation.stop_reason,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="model_extractions_replay_uq")
            )
            row = (
                await session.scalars(
                    select(ModelExtractionRow).where(
                        ModelExtractionRow.document_version_id == result.document_version_id,
                        ModelExtractionRow.route == result.config.route.value,
                        ModelExtractionRow.model_id == result.config.model_id,
                        ModelExtractionRow.prompt_version == result.config.prompt_version,
                        ModelExtractionRow.schema_version == result.config.schema_version,
                        ModelExtractionRow.input_sha256 == result.input_sha256,
                    )
                )
            ).one()
            for candidate in result.candidates:
                await session.execute(
                    insert(EvidenceCandidateRow)
                    .values(
                        id=uuid4(),
                        model_extraction_id=row.id,
                        candidate_id=candidate.candidate_id,
                        fact_path=candidate.fact_path,
                        value=candidate.value,
                        normalized_value=candidate.normalized_value,
                        evidence_refs=list(candidate.evidence_refs),
                        confidence=candidate.confidence,
                        producer=candidate.producer,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(constraint="evidence_candidates_candidate_id_uq")
                )
        stored = await self.find(
            result.document_version_id,
            result.config,
            result.input_sha256,
        )
        if stored is None:
            raise RuntimeError("Structured extraction was not persisted.")
        return stored


def _to_result(
    row: ModelExtractionRow,
    candidate_rows: Sequence[EvidenceCandidateRow],
) -> ComplexExtractionResult:
    config = ModelRouteConfig(
        route=ModelRoute(row.route),
        model_id=row.model_id,
        region=row.region,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        enabled=True,
        evaluation_approved=True,
    )
    return ComplexExtractionResult(
        document_version_id=row.document_version_id,
        input_sha256=row.input_sha256,
        config=config,
        invocation=ModelInvocation(
            raw_output={},
            provider_request_id=row.provider_request_id,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            latency_ms=row.latency_ms,
            stop_reason=row.stop_reason,
        ),
        candidates=tuple(
            EvidenceCandidate.model_validate(
                {
                    "candidate_id": candidate.candidate_id,
                    "fact_path": candidate.fact_path,
                    "value": candidate.value,
                    "normalized_value": candidate.normalized_value,
                    "evidence_refs": candidate.evidence_refs,
                    "confidence": candidate.confidence,
                    "producer": candidate.producer,
                    "model_id": config.model_id,
                    "route": config.route,
                    "prompt_version": config.prompt_version,
                    "schema_version": config.schema_version,
                }
            )
            for candidate in candidate_rows
        ),
    )
