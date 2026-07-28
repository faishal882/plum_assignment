from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID


class UploadSource(Protocol):
    filename: str | None
    content_type: str | None

    async def read(self, size: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class StoredDocument:
    storage_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    page_count: int
    sha256: str
    relative_path: Path


@dataclass(frozen=True, slots=True)
class UploadLimits:
    max_documents: int = 10
    max_file_bytes: int = 20 * 1024 * 1024
    max_claim_bytes: int = 50 * 1024 * 1024
    max_pages: int = 10
    chunk_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("max_documents", self.max_documents),
            ("max_file_bytes", self.max_file_bytes),
            ("max_claim_bytes", self.max_claim_bytes),
            ("max_pages", self.max_pages),
            ("chunk_bytes", self.chunk_bytes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")


class DocumentStore(Protocol):
    async def store_all(self, uploads: list[UploadSource]) -> tuple[StoredDocument, ...]: ...

    async def delete_all(self, documents: tuple[StoredDocument, ...]) -> None: ...


class DocumentIngestionError(Exception):
    code = "DOCUMENT_INGESTION_FAILED"

    def __init__(self, message: str, upload_index: int | None = None) -> None:
        self.message = message
        self.upload_index = upload_index
        super().__init__(message)


class TooManyDocumentsError(DocumentIngestionError):
    code = "TOO_MANY_DOCUMENTS"


class FileTooLargeError(DocumentIngestionError):
    code = "DOCUMENT_TOO_LARGE"


class ClaimUploadTooLargeError(DocumentIngestionError):
    code = "CLAIM_UPLOAD_TOO_LARGE"


class UnsupportedDocumentError(DocumentIngestionError):
    code = "UNSUPPORTED_DOCUMENT"


class CorruptDocumentError(DocumentIngestionError):
    code = "CORRUPT_DOCUMENT"


class EncryptedDocumentError(DocumentIngestionError):
    code = "ENCRYPTED_DOCUMENT"


class DocumentPageLimitError(DocumentIngestionError):
    code = "DOCUMENT_PAGE_LIMIT_EXCEEDED"


class UnsafeStorageError(DocumentIngestionError):
    code = "UNSAFE_DOCUMENT_STORAGE"
