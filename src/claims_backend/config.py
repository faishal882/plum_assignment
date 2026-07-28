from dataclasses import dataclass
from os import environ
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    data_root: Path = Path("data/documents")
    max_documents: int = 10
    max_file_bytes: int = 20 * 1024 * 1024
    max_claim_bytes: int = 50 * 1024 * 1024
    max_document_pages: int = 10
    upload_chunk_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("max_documents", self.max_documents),
            ("max_file_bytes", self.max_file_bytes),
            ("max_claim_bytes", self.max_claim_bytes),
            ("max_document_pages", self.max_document_pages),
            ("upload_chunk_bytes", self.upload_chunk_bytes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=environ.get(
                "CLAIMS_DATABASE_URL",
                "postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
            ),
            data_root=Path(environ.get("CLAIMS_DATA_ROOT", "data/documents")),
            max_documents=_environment_integer("CLAIMS_MAX_DOCUMENTS", 10),
            max_file_bytes=_environment_integer(
                "CLAIMS_MAX_FILE_BYTES",
                20 * 1024 * 1024,
            ),
            max_claim_bytes=_environment_integer(
                "CLAIMS_MAX_CLAIM_BYTES",
                50 * 1024 * 1024,
            ),
            max_document_pages=_environment_integer("CLAIMS_MAX_DOCUMENT_PAGES", 10),
            upload_chunk_bytes=_environment_integer(
                "CLAIMS_UPLOAD_CHUNK_BYTES",
                1024 * 1024,
            ),
        )


def _environment_integer(name: str, default: int) -> int:
    value = int(environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
