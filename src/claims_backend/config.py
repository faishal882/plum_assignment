from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import dotenv_values, find_dotenv, load_dotenv

_REQUIRED_ENVIRONMENT_KEYS = (
    "CLAIMS_DATABASE_URL",
    "CLAIMS_DATA_ROOT",
    "CLAIMS_MAX_DOCUMENTS",
    "CLAIMS_MAX_FILE_BYTES",
    "CLAIMS_MAX_CLAIM_BYTES",
    "CLAIMS_MAX_DOCUMENT_PAGES",
    "CLAIMS_UPLOAD_CHUNK_BYTES",
    "CLAIMS_MAX_TEXTRACT_PAGE_BYTES",
    "CLAIMS_PAGE_RENDER_DPI",
    "CLAIMS_AWS_REGION",
    "CLAIMS_BEDROCK_REGION",
    "CLAIMS_BEDROCK_MODEL_ID",
)


class ConfigurationError(ValueError):
    pass


def load_environment(env_file: Path | None = None) -> Path | None:
    resolved = _resolve_environment_file(env_file)
    if resolved is None:
        return None
    load_dotenv(dotenv_path=resolved, override=False)
    return resolved


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
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        values = _configuration_values(env_file)
        missing = [name for name in _REQUIRED_ENVIRONMENT_KEYS if not values.get(name)]
        if missing:
            names = ", ".join(sorted(missing))
            raise ConfigurationError(
                f"Missing required configuration: {names}. "
                "Copy .env.example to .env and set every value."
            )
        return cls(
            database_url=_environment_value(values, "CLAIMS_DATABASE_URL"),
            data_root=Path(_environment_value(values, "CLAIMS_DATA_ROOT")),
            max_documents=_environment_integer(values, "CLAIMS_MAX_DOCUMENTS"),
            max_file_bytes=_environment_integer(values, "CLAIMS_MAX_FILE_BYTES"),
            max_claim_bytes=_environment_integer(values, "CLAIMS_MAX_CLAIM_BYTES"),
            max_document_pages=_environment_integer(values, "CLAIMS_MAX_DOCUMENT_PAGES"),
            upload_chunk_bytes=_environment_integer(values, "CLAIMS_UPLOAD_CHUNK_BYTES"),
            max_textract_page_bytes=_environment_integer(values, "CLAIMS_MAX_TEXTRACT_PAGE_BYTES"),
            page_render_dpi=_environment_integer(values, "CLAIMS_PAGE_RENDER_DPI"),
            aws_region=_environment_value(values, "CLAIMS_AWS_REGION"),
            bedrock_region=_environment_value(values, "CLAIMS_BEDROCK_REGION"),
            bedrock_model_id=_environment_value(values, "CLAIMS_BEDROCK_MODEL_ID"),
        )


def _resolve_environment_file(env_file: Path | None) -> Path | None:
    resolved = env_file
    if resolved is None:
        discovered = find_dotenv(usecwd=True)
        resolved = Path(discovered) if discovered else None
    if resolved is not None and not resolved.is_file():
        raise ConfigurationError(f"Environment file does not exist: {resolved}")
    return resolved


def _configuration_values(env_file: Path | None) -> dict[str, str | None]:
    resolved = _resolve_environment_file(env_file)
    values = {} if resolved is None else dict(dotenv_values(resolved))
    values.update(environ)
    return values


def _environment_value(values: Mapping[str, str | None], name: str) -> str:
    value = values.get(name)
    if not value:
        raise ConfigurationError(f"{name} must be configured")
    return value


def _environment_integer(values: Mapping[str, str | None], name: str) -> int:
    raw = _environment_value(values, name)
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value
