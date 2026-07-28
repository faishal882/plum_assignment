import os
import warnings
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from claims_backend.application.documents import (
    ClaimUploadTooLargeError,
    CorruptDocumentError,
    DocumentIngestionError,
    DocumentPageLimitError,
    EncryptedDocumentError,
    FileTooLargeError,
    StoredDocument,
    TooManyDocumentsError,
    UnsafeStorageError,
    UnsupportedDocumentError,
    UploadLimits,
    UploadSource,
)

_MEDIA_SUFFIX = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


class LocalDocumentStore:
    def __init__(self, data_root: Path, limits: UploadLimits | None = None) -> None:
        self._limits = limits or UploadLimits()
        if data_root.exists() and data_root.is_symlink():
            raise UnsafeStorageError("The configured document root cannot be a symlink.")
        data_root.mkdir(parents=True, exist_ok=True)
        self._root = data_root.resolve(strict=True)
        self._staging = self._ensure_directory(Path(".staging"))
        self._objects = self._ensure_directory(Path("objects"))

    async def store_all(self, uploads: list[UploadSource]) -> tuple[StoredDocument, ...]:
        if not uploads:
            raise CorruptDocumentError("At least one document is required.")
        if len(uploads) > self._limits.max_documents:
            raise TooManyDocumentsError(
                f"A claim can contain at most {self._limits.max_documents} documents."
            )

        stored: list[StoredDocument] = []
        aggregate_size = 0
        try:
            for index, upload in enumerate(uploads):
                document = await self._store_one(upload, index, aggregate_size)
                aggregate_size += document.size_bytes
                stored.append(document)
        except Exception:
            await self.delete_all(tuple(stored))
            raise
        return tuple(stored)

    async def delete_all(self, documents: tuple[StoredDocument, ...]) -> None:
        for document in documents:
            path = self._safe_absolute(document.relative_path)
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise UnsafeStorageError(
                    "Failed to remove an unreferenced document artifact."
                ) from error

    async def _store_one(
        self,
        upload: UploadSource,
        upload_index: int,
        aggregate_size: int,
    ) -> StoredDocument:
        storage_id = uuid4()
        staging_path = self._staging / f"{storage_id}.upload"
        final_path: Path | None = None
        digest = sha256()
        size_bytes = 0
        header = b""

        try:
            with staging_path.open("xb") as target:
                while chunk := await upload.read(self._limits.chunk_bytes):
                    size_bytes += len(chunk)
                    if size_bytes > self._limits.max_file_bytes:
                        raise FileTooLargeError(
                            f"Document exceeds the {self._limits.max_file_bytes} byte limit.",
                            upload_index,
                        )
                    if aggregate_size + size_bytes > self._limits.max_claim_bytes:
                        raise ClaimUploadTooLargeError(
                            f"Claim uploads exceed the {self._limits.max_claim_bytes} byte limit.",
                            upload_index,
                        )
                    if len(header) < 16:
                        header = (header + chunk)[:16]
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            if size_bytes == 0:
                raise CorruptDocumentError("Document is empty.", upload_index)

            media_type = _detect_media_type(header, upload_index)
            page_count = self._validate(staging_path, media_type, upload_index)
            content_hash = digest.hexdigest()
            relative_parent = Path("objects") / content_hash[:2] / content_hash
            final_parent = self._ensure_directory(relative_parent)
            final_path = final_parent / f"{storage_id}{_MEDIA_SUFFIX[media_type]}"
            os.replace(staging_path, final_path)
            final_path.chmod(0o440)
            _fsync_directory(final_parent)

            return StoredDocument(
                storage_id=storage_id,
                original_filename=_safe_filename(upload.filename),
                media_type=media_type,
                size_bytes=size_bytes,
                page_count=page_count,
                sha256=content_hash,
                relative_path=final_path.relative_to(self._root),
            )
        except DocumentIngestionError:
            staging_path.unlink(missing_ok=True)
            if final_path is not None:
                final_path.unlink(missing_ok=True)
            raise
        except OSError as error:
            staging_path.unlink(missing_ok=True)
            if final_path is not None:
                final_path.unlink(missing_ok=True)
            raise UnsafeStorageError(
                "Document could not be written safely.",
                upload_index,
            ) from error

    def _validate(self, path: Path, media_type: str, upload_index: int) -> int:
        if media_type == "application/pdf":
            page_count = _validate_pdf(path, upload_index)
        else:
            page_count = _validate_image(path, media_type, upload_index)
        if page_count > self._limits.max_pages:
            raise DocumentPageLimitError(
                f"Document exceeds the {self._limits.max_pages} page limit.",
                upload_index,
            )
        return page_count

    def _ensure_directory(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise UnsafeStorageError("Document storage path is unsafe.")
        current = self._root
        for part in relative_path.parts:
            current = current / part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            if current.is_symlink() or not current.is_dir():
                raise UnsafeStorageError("Document storage contains an unsafe path component.")
            if not current.resolve(strict=True).is_relative_to(self._root):
                raise UnsafeStorageError("Document storage path escaped its configured root.")
        return current

    def _safe_absolute(self, relative_path: Path) -> Path:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise UnsafeStorageError("Document storage path is unsafe.")
        candidate = self._root / relative_path
        if not candidate.parent.resolve(strict=True).is_relative_to(self._root):
            raise UnsafeStorageError("Document storage path escaped its configured root.")
        return candidate


def _detect_media_type(header: bytes, upload_index: int) -> str:
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise UnsupportedDocumentError(
        "Only PDF, JPEG, and PNG documents are supported.",
        upload_index,
    )


def _validate_pdf(path: Path, upload_index: int) -> int:
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted:
                raise EncryptedDocumentError(
                    "Encrypted PDF documents are not supported.",
                    upload_index,
                )
            page_count = len(reader.pages)
            for page in reader.pages:
                _ = page.mediabox
    except EncryptedDocumentError:
        raise
    except (PdfReadError, OSError, ValueError) as error:
        raise CorruptDocumentError(
            "PDF structure is invalid or incomplete.",
            upload_index,
        ) from error
    if page_count == 0:
        raise CorruptDocumentError("PDF contains no pages.", upload_index)
    return page_count


def _validate_image(path: Path, media_type: str, upload_index: int) -> int:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                actual_media_type = Image.MIME.get(image.format or "")
                page_count = getattr(image, "n_frames", 1)
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise CorruptDocumentError("Image dimensions are unsafe.", upload_index) from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise CorruptDocumentError(
            "Image structure is invalid or incomplete.",
            upload_index,
        ) from error
    if actual_media_type != media_type:
        raise CorruptDocumentError("Image signature and structure do not agree.", upload_index)
    return page_count


def _safe_filename(filename: str | None) -> str:
    label = (filename or "upload").replace("\\", "/").split("/")[-1]
    label = "".join(
        character for character in label if character.isprintable() and character != "\x00"
    )
    return label[:255] or "upload"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
