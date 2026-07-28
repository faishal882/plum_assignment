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
    max_textract_page_bytes: int = 5 * 1024 * 1024
    page_render_dpi: int = 180
    aws_region: str = "ap-south-1"
    bedrock_region: str = "us-west-2"
    bedrock_model_id: str = "qwen.qwen3-235b-a22b-2507-v1:0"

    def __post_init__(self) -> None:
        for name, value in (
            ("max_documents", self.max_documents),
            ("max_file_bytes", self.max_file_bytes),
            ("max_claim_bytes", self.max_claim_bytes),
            ("max_document_pages", self.max_document_pages),
            ("upload_chunk_bytes", self.upload_chunk_bytes),
            ("max_textract_page_bytes", self.max_textract_page_bytes),
            ("page_render_dpi", self.page_render_dpi),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if not self.aws_region or not self.bedrock_region or not self.bedrock_model_id:
            raise ValueError("AWS and Bedrock configuration cannot be empty")

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
            max_textract_page_bytes=_environment_integer(
                "CLAIMS_MAX_TEXTRACT_PAGE_BYTES",
                5 * 1024 * 1024,
            ),
            page_render_dpi=_environment_integer("CLAIMS_PAGE_RENDER_DPI", 180),
            aws_region=environ.get("CLAIMS_AWS_REGION", "ap-south-1"),
            bedrock_region=environ.get("CLAIMS_BEDROCK_REGION", "us-west-2"),
            bedrock_model_id=environ.get(
                "CLAIMS_BEDROCK_MODEL_ID",
                "qwen.qwen3-235b-a22b-2507-v1:0",
            ),
        )


def _environment_integer(name: str, default: int) -> int:
    value = int(environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
