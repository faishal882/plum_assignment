from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


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
