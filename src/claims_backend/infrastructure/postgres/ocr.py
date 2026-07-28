from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.intelligence import PageArtifact
from claims_backend.domain.evidence import DocumentRole, NormalizedRegion
from claims_backend.domain.ocr import (
    OcrObservation,
    OcrObservationKind,
    OcrPageResult,
)
from claims_backend.infrastructure.postgres.models import (
    OcrObservationRow,
    OcrPageResultRow,
)


class PostgresOcrRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def has_result(
        self,
        page_artifact_id: UUID,
        provider_name: str,
        provider_version: str,
        role: DocumentRole,
    ) -> bool:
        async with self._session_factory() as session:
            result_id = await session.scalar(
                select(OcrPageResultRow.id).where(
                    OcrPageResultRow.page_artifact_id == page_artifact_id,
                    OcrPageResultRow.provider_name == provider_name,
                    OcrPageResultRow.provider_version == provider_version,
                    OcrPageResultRow.document_role == role.value,
                )
            )
        return result_id is not None

    async def save(
        self,
        artifact: PageArtifact,
        provider_name: str,
        provider_version: str,
        role: DocumentRole,
        result: OcrPageResult,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(OcrPageResultRow)
                .values(
                    id=uuid4(),
                    page_artifact_id=artifact.id,
                    document_version_id=artifact.document_version_id,
                    page_number=artifact.page_number,
                    provider_name=provider_name,
                    provider_version=provider_version,
                    document_role=role.value,
                    profile=result.profile.value,
                    provider_request_id=result.provider_request_id,
                    retry_attempts=result.retry_attempts,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="ocr_page_results_artifact_provider_uq")
            )
            page_result_id = (
                await session.scalars(
                    select(OcrPageResultRow.id).where(
                        OcrPageResultRow.page_artifact_id == artifact.id,
                        OcrPageResultRow.provider_name == provider_name,
                        OcrPageResultRow.provider_version == provider_version,
                        OcrPageResultRow.document_role == role.value,
                    )
                )
            ).one()
            for observation in result.observations:
                await session.execute(
                    insert(OcrObservationRow)
                    .values(
                        id=uuid4(),
                        ocr_page_result_id=page_result_id,
                        observation_id=observation.observation_id,
                        document_version_id=observation.document_version_id,
                        page_number=observation.page_number,
                        kind=observation.kind.value,
                        text=observation.text,
                        confidence=observation.confidence,
                        region=observation.region.model_dump(mode="json"),
                        source_id=observation.source_id,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(constraint="ocr_observations_observation_id_uq")
                )

    async def list_observations(
        self,
        document_version_id: UUID,
        role: DocumentRole | None = None,
    ) -> tuple[OcrObservation, ...]:
        async with self._session_factory() as session:
            statement = (
                select(OcrObservationRow)
                .join(OcrPageResultRow)
                .where(OcrObservationRow.document_version_id == document_version_id)
            )
            if role is not None:
                statement = statement.where(OcrPageResultRow.document_role == role.value)
            rows = (await session.scalars(statement)).all()
        observations = tuple(_to_domain(row) for row in rows)
        return tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.page_number,
                    item.region.y,
                    item.region.x,
                    item.kind.value,
                    item.source_id,
                ),
            )
        )


def _to_domain(row: OcrObservationRow) -> OcrObservation:
    return OcrObservation(
        observation_id=row.observation_id,
        document_version_id=row.document_version_id,
        page_number=row.page_number,
        kind=OcrObservationKind(row.kind),
        text=row.text,
        confidence=row.confidence,
        region=NormalizedRegion.model_validate(row.region),
        source_id=row.source_id,
    )
