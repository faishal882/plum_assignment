import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from claims_backend.application.intelligence import (
    RenderedPage,
    RenderedPageTooLargeError,
    SourceDocument,
    SourceDocumentChangedError,
)

_RENDER_VERSION = "pdfium-jpeg-v1"


class LocalPageRenderer:
    def __init__(
        self,
        data_root: Path,
        *,
        max_page_bytes: int,
        render_dpi: int = 180,
    ) -> None:
        if max_page_bytes <= 0 or render_dpi <= 0:
            raise ValueError("Page rendering limits must be greater than zero.")
        self._root = data_root.resolve(strict=True)
        self._max_page_bytes = max_page_bytes
        self._scale = render_dpi / 72

    async def render(self, document: SourceDocument) -> tuple[RenderedPage, ...]:
        return await asyncio.to_thread(self._render_sync, document)

    def _render_sync(self, document: SourceDocument) -> tuple[RenderedPage, ...]:
        path = self._source_path(document.relative_path)
        source = path.read_bytes()
        if sha256(source).hexdigest() != document.sha256:
            raise SourceDocumentChangedError("Sealed source document hash does not match.")
        if document.media_type == "application/pdf":
            images = self._render_pdf(path)
        elif document.media_type in {"image/jpeg", "image/png"}:
            images = self._render_image(path)
        else:
            raise SourceDocumentChangedError("Source document media type is unsupported.")
        if len(images) != document.page_count:
            raise SourceDocumentChangedError("Source document page count changed.")
        return tuple(
            self._page(document, page_number, image)
            for page_number, image in enumerate(images, start=1)
        )

    def _render_pdf(self, path: Path) -> list[Image.Image]:
        document = pdfium.PdfDocument(path)
        images: list[Image.Image] = []
        try:
            for index in range(len(document)):
                page = document[index]
                bitmap = None
                try:
                    bitmap = page.render(
                        scale=self._scale,
                        rotation=0,
                        draw_annots=True,
                        optimize_mode="print",
                    )
                    images.append(bitmap.to_pil().convert("RGB").copy())
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        finally:
            document.close()
        return images

    def _render_image(self, path: Path) -> list[Image.Image]:
        images: list[Image.Image] = []
        with Image.open(path) as source:
            for index in range(getattr(source, "n_frames", 1)):
                source.seek(index)
                images.append(source.convert("RGB").copy())
        return images

    def _page(
        self,
        document: SourceDocument,
        page_number: int,
        image: Image.Image,
    ) -> RenderedPage:
        content, width, height = self._encode_bounded(image, page_number)
        return RenderedPage(
            document_id=document.document_id,
            document_version_id=document.document_version_id,
            page_number=page_number,
            original_sha256=document.sha256,
            media_type="image/jpeg",
            content=content,
            sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            width=width,
            height=height,
            render_version=_RENDER_VERSION,
        )

    def _encode_bounded(
        self,
        source: Image.Image,
        page_number: int,
    ) -> tuple[bytes, int, int]:
        image = source
        for _ in range(8):
            for quality in (90, 75, 60, 45):
                output = BytesIO()
                image.save(
                    output,
                    format="JPEG",
                    quality=quality,
                    optimize=False,
                    progressive=False,
                    subsampling=2,
                )
                content = output.getvalue()
                if len(content) <= self._max_page_bytes:
                    return content, image.width, image.height
            if min(image.size) <= 256:
                break
            image = image.resize(
                (
                    max(1, int(image.width * 0.8)),
                    max(1, int(image.height * 0.8)),
                ),
                Image.Resampling.LANCZOS,
            )
        raise RenderedPageTooLargeError(page_number, self._max_page_bytes)

    def _source_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise SourceDocumentChangedError("Source document path is unsafe.")
        candidate = self._root / relative
        if candidate.is_symlink() or not candidate.resolve(strict=True).is_relative_to(self._root):
            raise SourceDocumentChangedError("Source document path escaped its root.")
        return candidate
