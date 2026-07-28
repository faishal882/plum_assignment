from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from claims_backend.application.documents import (
    ClaimUploadTooLargeError,
    CorruptDocumentError,
    DocumentPageLimitError,
    EncryptedDocumentError,
    FileTooLargeError,
    TooManyDocumentsError,
    UnsafeStorageError,
    UnsupportedDocumentError,
    UploadLimits,
    UploadSource,
)
from claims_backend.infrastructure.local_documents import LocalDocumentStore


class MemoryUpload(UploadSource):
    def __init__(self, filename: str, content_type: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content
        self._offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class InterruptedUpload(MemoryUpload):
    async def read(self, size: int) -> bytes:
        if self._offset:
            raise OSError("injected read failure")
        return await super().read(size)


@pytest.mark.asyncio
async def test_supported_documents_are_validated_and_stored_by_content(
    tmp_path,
) -> None:
    pdf = _pdf_bytes()
    jpeg = _image_bytes("JPEG")
    png = _image_bytes("PNG")
    store = LocalDocumentStore(tmp_path)

    stored = await store.store_all(
        [
            MemoryUpload("../../claim.exe", "application/octet-stream", pdf),
            MemoryUpload("scan.bin", "application/octet-stream", jpeg),
            MemoryUpload("report.txt", "text/plain", png),
        ]
    )

    assert [document.media_type for document in stored] == [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]
    assert [document.page_count for document in stored] == [1, 1, 1]
    assert [document.original_filename for document in stored] == [
        "claim.exe",
        "scan.bin",
        "report.txt",
    ]
    for document, content in zip(stored, (pdf, jpeg, png), strict=True):
        assert document.sha256 == sha256(content).hexdigest()
        assert document.size_bytes == len(content)
        path = tmp_path / document.relative_path
        assert path.is_file()
        assert path.read_bytes() == content
        assert document.sha256 in document.relative_path.as_posix()
        assert document.original_filename not in document.relative_path.as_posix()


@pytest.mark.asyncio
async def test_uploads_are_read_in_bounded_chunks(tmp_path: Path) -> None:
    content = _image_bytes("PNG") + (b"trailing-safe-data" * 32)
    upload = MemoryUpload("scan.png", "image/png", content)
    limits = UploadLimits(chunk_bytes=64)

    await LocalDocumentStore(tmp_path, limits).store_all([upload])

    assert len(upload.read_sizes) > 2
    assert set(upload.read_sizes) == {64}


@pytest.mark.asyncio
async def test_document_count_and_byte_limits_remove_all_artifacts(tmp_path: Path) -> None:
    png = _image_bytes("PNG")

    with pytest.raises(TooManyDocumentsError):
        await LocalDocumentStore(
            tmp_path / "count",
            UploadLimits(max_documents=2),
        ).store_all(
            [
                MemoryUpload("one.png", "image/png", png),
                MemoryUpload("two.png", "image/png", png),
                MemoryUpload("three.png", "image/png", png),
            ]
        )

    with pytest.raises(FileTooLargeError):
        await LocalDocumentStore(
            tmp_path / "file-size",
            UploadLimits(max_file_bytes=len(png) - 1),
        ).store_all([MemoryUpload("large.png", "image/png", png)])

    with pytest.raises(ClaimUploadTooLargeError):
        await LocalDocumentStore(
            tmp_path / "claim-size",
            UploadLimits(max_file_bytes=len(png), max_claim_bytes=(len(png) * 2) - 1),
        ).store_all(
            [
                MemoryUpload("one.png", "image/png", png),
                MemoryUpload("two.png", "image/png", png),
            ]
        )

    assert _matching_paths(tmp_path, "*.png") == []
    assert _matching_paths(tmp_path, "*.upload") == []


@pytest.mark.asyncio
async def test_invalid_documents_have_specific_failure_types(tmp_path: Path) -> None:
    store = LocalDocumentStore(tmp_path, UploadLimits(max_pages=10))

    with pytest.raises(UnsupportedDocumentError):
        await store.store_all([MemoryUpload("notes.txt", "text/plain", b"not a document")])

    with pytest.raises(CorruptDocumentError):
        await store.store_all([MemoryUpload("broken.pdf", "application/pdf", b"%PDF- broken")])

    with pytest.raises(EncryptedDocumentError):
        await store.store_all(
            [MemoryUpload("locked.pdf", "application/pdf", _pdf_bytes(password="secret"))]
        )

    with pytest.raises(DocumentPageLimitError):
        await store.store_all(
            [MemoryUpload("long.pdf", "application/pdf", _pdf_bytes(page_count=11))]
        )

    assert _matching_paths(tmp_path, "*.upload") == []
    assert _matching_paths(tmp_path, "*.pdf") == []


@pytest.mark.asyncio
async def test_same_content_creates_distinct_immutable_document_versions(tmp_path: Path) -> None:
    pdf = _pdf_bytes()
    store = LocalDocumentStore(tmp_path)

    first, second = await store.store_all(
        [
            MemoryUpload("first.pdf", "application/pdf", pdf),
            MemoryUpload("second.pdf", "application/pdf", pdf),
        ]
    )

    assert first.sha256 == second.sha256
    assert first.relative_path != second.relative_path
    for document in (first, second):
        mode = (tmp_path / document.relative_path).stat().st_mode
        assert mode & 0o222 == 0


@pytest.mark.asyncio
async def test_symlink_components_cannot_escape_the_data_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeStorageError):
        LocalDocumentStore(linked_root)

    real_root = tmp_path / "real-root"
    store = LocalDocumentStore(real_root)
    pdf = _pdf_bytes()
    digest = sha256(pdf).hexdigest()
    prefix = real_root / "objects" / digest[:2]
    prefix.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeStorageError):
        await store.store_all([MemoryUpload("../../escape.pdf", "application/pdf", pdf)])

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_interrupted_batch_removes_staging_and_previously_sealed_files(
    tmp_path: Path,
) -> None:
    pdf = _pdf_bytes()
    store = LocalDocumentStore(tmp_path, UploadLimits(chunk_bytes=64))

    with pytest.raises(UnsafeStorageError):
        await store.store_all(
            [
                MemoryUpload("complete.pdf", "application/pdf", pdf),
                InterruptedUpload("interrupted.pdf", "application/pdf", pdf),
            ]
        )

    assert list((tmp_path / ".staging").iterdir()) == []
    assert list((tmp_path / "objects").rglob("*.pdf")) == []


def _pdf_bytes(page_count: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _image_bytes(format_name: str) -> bytes:
    image = Image.new("RGB", (16, 16), color="white")
    output = BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


def _matching_paths(root: Path, pattern: str) -> list[Path]:
    return list(root.rglob(pattern))
