import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from claims_backend.domain.evidence import DocumentRole
from claims_backend.domain.ocr import OcrObservation, OcrPageResult


@dataclass(frozen=True, slots=True)
class SourceDocument:
    document_id: UUID
    document_version_id: UUID
    relative_path: str
    media_type: str
    sha256: str
    page_count: int


@dataclass(frozen=True, slots=True)
class RenderedPage:
    document_id: UUID
    document_version_id: UUID
    page_number: int
    original_sha256: str
    media_type: str
    content: bytes
    sha256: str
    size_bytes: int
    width: int
    height: int
    render_version: str


class PageRenderer(Protocol):
    async def render(self, document: SourceDocument) -> tuple[RenderedPage, ...]: ...


@dataclass(frozen=True, slots=True)
class PageArtifactDraft:
    page: RenderedPage
    relative_path: Path


@dataclass(frozen=True, slots=True)
class PageArtifact:
    id: UUID
    document_id: UUID
    document_version_id: UUID
    page_number: int
    original_sha256: str
    rendered_sha256: str
    relative_path: Path
    media_type: str
    size_bytes: int
    width: int
    height: int
    render_version: str


class PageArtifactStore(Protocol):
    async def store_all(
        self,
        pages: tuple[RenderedPage, ...],
    ) -> tuple[PageArtifactDraft, ...]: ...


class PageArtifactRepository(Protocol):
    async def list_for_document_version(
        self,
        document_version_id: UUID,
    ) -> tuple[PageArtifact, ...]: ...

    async def save_all(
        self,
        drafts: tuple[PageArtifactDraft, ...],
    ) -> tuple[PageArtifact, ...]: ...


class PageArtifactApplication:
    def __init__(
        self,
        renderer: PageRenderer,
        store: PageArtifactStore,
        repository: PageArtifactRepository,
    ) -> None:
        self._renderer = renderer
        self._store = store
        self._repository = repository

    async def process(self, document: SourceDocument) -> tuple[PageArtifact, ...]:
        existing = await self._repository.list_for_document_version(document.document_version_id)
        if existing:
            if len(existing) != document.page_count:
                raise PageRenderingError("Persisted page artifact set is incomplete.")
            return existing
        rendered = await self._renderer.render(document)
        drafts = await self._store.store_all(rendered)
        persisted = await self._repository.save_all(drafts)
        if len(persisted) != document.page_count:
            raise PageRenderingError("Rendered page artifact set is incomplete.")
        return persisted


class PageArtifactReader(Protocol):
    async def read(self, artifact: PageArtifact) -> RenderedPage: ...


class OcrProvider(Protocol):
    provider_name: str
    provider_version: str

    def analyze(
        self,
        page: RenderedPage,
        role: DocumentRole,
    ) -> OcrPageResult: ...


class OcrRepository(Protocol):
    async def has_result(
        self,
        page_artifact_id: UUID,
        provider_name: str,
        provider_version: str,
    ) -> bool: ...

    async def save(
        self,
        artifact: PageArtifact,
        provider_name: str,
        provider_version: str,
        result: OcrPageResult,
    ) -> None: ...

    async def list_observations(
        self,
        document_version_id: UUID,
    ) -> tuple[OcrObservation, ...]: ...


class OcrApplication:
    def __init__(
        self,
        reader: PageArtifactReader,
        provider: OcrProvider,
        repository: OcrRepository,
    ) -> None:
        self._reader = reader
        self._provider = provider
        self._repository = repository

    async def process(
        self,
        artifacts: tuple[PageArtifact, ...],
        role: DocumentRole,
    ) -> tuple[OcrObservation, ...]:
        if not artifacts:
            return ()
        document_version_id = artifacts[0].document_version_id
        if any(artifact.document_version_id != document_version_id for artifact in artifacts):
            raise ValueError("OCR artifacts must belong to one document version.")
        for artifact in sorted(artifacts, key=lambda item: item.page_number):
            exists = await self._repository.has_result(
                artifact.id,
                self._provider.provider_name,
                self._provider.provider_version,
            )
            if exists:
                continue
            page = await self._reader.read(artifact)
            result = await asyncio.to_thread(self._provider.analyze, page, role)
            await self._repository.save(
                artifact,
                self._provider.provider_name,
                self._provider.provider_version,
                result,
            )
        return await self._repository.list_observations(document_version_id)


class PageRenderingError(Exception):
    pass


class SourceDocumentChangedError(PageRenderingError):
    pass


class RenderedPageTooLargeError(PageRenderingError):
    def __init__(self, page_number: int, max_page_bytes: int) -> None:
        self.page_number = page_number
        self.max_page_bytes = max_page_bytes
        super().__init__(
            f"Rendered page {page_number} exceeds the {max_page_bytes} byte provider limit."
        )
