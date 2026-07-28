import asyncio
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from claims_backend.application.intelligence import PageArtifactDraft, RenderedPage


class LocalPageArtifactStore:
    def __init__(self, data_root: Path) -> None:
        self._root = data_root.resolve(strict=True)

    async def store_all(
        self,
        pages: tuple[RenderedPage, ...],
    ) -> tuple[PageArtifactDraft, ...]:
        return await asyncio.to_thread(self._store_all_sync, pages)

    def _store_all_sync(
        self,
        pages: tuple[RenderedPage, ...],
    ) -> tuple[PageArtifactDraft, ...]:
        return tuple(self._store_one(page) for page in pages)

    def _store_one(self, page: RenderedPage) -> PageArtifactDraft:
        relative = (
            Path("pages")
            / str(page.document_version_id)
            / page.render_version
            / f"page-{page.page_number:04d}-{page.sha256}.jpg"
        )
        target = self._safe_parent(relative.parent) / relative.name
        if target.exists():
            if target.is_symlink() or sha256(target.read_bytes()).hexdigest() != page.sha256:
                raise OSError("Persisted page artifact content changed.")
        else:
            temporary = target.with_name(f".{target.name}.{uuid4()}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(page.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                target.chmod(0o440)
                _fsync_directory(target.parent)
            finally:
                temporary.unlink(missing_ok=True)
        return PageArtifactDraft(page=page, relative_path=relative)

    def _safe_parent(self, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise OSError("Page artifact path is unsafe.")
        current = self._root
        for part in relative.parts:
            current = current / part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            if current.is_symlink() or not current.resolve(strict=True).is_relative_to(self._root):
                raise OSError("Page artifact path escaped its root.")
        return current


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
