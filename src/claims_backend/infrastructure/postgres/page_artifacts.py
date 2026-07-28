from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.intelligence import PageArtifact, PageArtifactDraft
from claims_backend.infrastructure.postgres.models import DocumentPageArtifactRow


class PostgresPageArtifactRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for_document_version(
        self,
        document_version_id: UUID,
    ) -> tuple[PageArtifact, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(DocumentPageArtifactRow)
                    .where(DocumentPageArtifactRow.document_version_id == document_version_id)
                    .order_by(DocumentPageArtifactRow.page_number)
                )
            ).all()
        return tuple(_to_domain(row) for row in rows)

    async def save_all(
        self,
        drafts: tuple[PageArtifactDraft, ...],
    ) -> tuple[PageArtifact, ...]:
        if not drafts:
            return ()
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            for draft in drafts:
                page = draft.page
                await session.execute(
                    insert(DocumentPageArtifactRow)
                    .values(
                        id=uuid4(),
                        document_id=page.document_id,
                        document_version_id=page.document_version_id,
                        page_number=page.page_number,
                        original_sha256=page.original_sha256,
                        rendered_sha256=page.sha256,
                        relative_path=draft.relative_path.as_posix(),
                        media_type=page.media_type,
                        size_bytes=page.size_bytes,
                        width=page.width,
                        height=page.height,
                        render_version=page.render_version,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        constraint="document_page_artifacts_version_page_render_uq"
                    )
                )
        return await self.list_for_document_version(drafts[0].page.document_version_id)


def _to_domain(row: DocumentPageArtifactRow) -> PageArtifact:
    return PageArtifact(
        id=row.id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        page_number=row.page_number,
        original_sha256=row.original_sha256,
        rendered_sha256=row.rendered_sha256,
        relative_path=Path(row.relative_path),
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        width=row.width,
        height=row.height,
        render_version=row.render_version,
    )
