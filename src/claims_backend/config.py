from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import dotenv_values, find_dotenv, load_dotenv

from claims_backend.runtime.profiles import ExecutionProfile, resolve_execution_profile

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
    "CLAIMS_TEXTRACT_TIMEOUT_SECONDS",
    "CLAIMS_TEXTRACT_CONCURRENCY_LIMIT",
    "CLAIMS_BEDROCK_REGION",
    "CLAIMS_BEDROCK_MODEL_ID",
    "CLAIMS_BEDROCK_TIMEOUT_SECONDS",
    "CLAIMS_BEDROCK_CONCURRENCY_LIMIT",
    "CLAIMS_PROVIDER_MAX_ATTEMPTS",
    "CLAIMS_RETRY_BASE_SECONDS",
    "CLAIMS_RETRY_MAX_SECONDS",
    "CLAIMS_RETRY_JITTER_RATIO",
    "CLAIMS_OBSERVABILITY_ENABLED",
    "CLAIMS_PHOENIX_ENDPOINT",
    "CLAIMS_PHOENIX_PROJECT",
    "CLAIMS_LOG_ROOT",
    "CLAIMS_LOG_MAX_BYTES",
    "CLAIMS_LOG_BACKUP_COUNT",
    "CLAIMS_EXECUTION_PROFILE",
    "CLAIMS_RUN_LIVE_AWS",
    "CLAIMS_WORKER_ID",
    "CLAIMS_WORKER_POLL_SECONDS",
    "CLAIMS_WORKER_LEASE_SECONDS",
    "CLAIMS_WORKER_SHUTDOWN_SECONDS",
    "CLAIMS_INJECT_ANOMALY_ENRICHMENT_FAILURE",
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
    textract_timeout_seconds: int = 30
    textract_concurrency_limit: int = 2
    bedrock_region: str = "us-west-2"
    bedrock_model_id: str = "qwen.qwen3-235b-a22b-2507-v1:0"
    bedrock_timeout_seconds: int = 90
    bedrock_concurrency_limit: int = 2
    provider_max_attempts: int = 3
    retry_base_seconds: int = 2
    retry_max_seconds: int = 60
    retry_jitter_ratio: float = 0.25
    observability_enabled: bool = False
    phoenix_endpoint: str = "http://127.0.0.1:6006/v1/traces"
    phoenix_project: str = "plum-claims-local"
    log_root: Path = Path("data/logs")
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    execution_profile: ExecutionProfile = ExecutionProfile.RECORDED_LOCAL
    run_live_aws: bool = False
    worker_id: str = "claims-worker-local"
    worker_poll_seconds: int = 1
    worker_lease_seconds: int = 300
    worker_shutdown_seconds: int = 120
    inject_anomaly_enrichment_failure: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("max_documents", self.max_documents),
            ("max_file_bytes", self.max_file_bytes),
            ("max_claim_bytes", self.max_claim_bytes),
            ("max_document_pages", self.max_document_pages),
            ("upload_chunk_bytes", self.upload_chunk_bytes),
            ("max_textract_page_bytes", self.max_textract_page_bytes),
            ("page_render_dpi", self.page_render_dpi),
            ("textract_timeout_seconds", self.textract_timeout_seconds),
            ("textract_concurrency_limit", self.textract_concurrency_limit),
            ("bedrock_timeout_seconds", self.bedrock_timeout_seconds),
            ("bedrock_concurrency_limit", self.bedrock_concurrency_limit),
            ("provider_max_attempts", self.provider_max_attempts),
            ("retry_base_seconds", self.retry_base_seconds),
            ("retry_max_seconds", self.retry_max_seconds),
            ("log_max_bytes", self.log_max_bytes),
            ("log_backup_count", self.log_backup_count),
            ("worker_poll_seconds", self.worker_poll_seconds),
            ("worker_lease_seconds", self.worker_lease_seconds),
            ("worker_shutdown_seconds", self.worker_shutdown_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.provider_max_attempts > 3:
            raise ValueError("provider_max_attempts cannot exceed three")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds cannot be less than retry_base_seconds")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("retry_jitter_ratio must be between 0 and 1")
        if not self.aws_region or not self.bedrock_region or not self.bedrock_model_id:
            raise ValueError("AWS and Bedrock configuration cannot be empty")
        if not self.phoenix_endpoint or not self.phoenix_project:
            raise ValueError("Phoenix configuration cannot be empty")
        if not self.worker_id.strip():
            raise ValueError("worker_id cannot be empty")
        profile = resolve_execution_profile(
            str(self.execution_profile),
            run_live_aws=self.run_live_aws,
        )
        object.__setattr__(self, "execution_profile", profile)
        if self.inject_anomaly_enrichment_failure and (
            self.execution_profile is not ExecutionProfile.RECORDED_LOCAL
        ):
            raise ValueError("Anomaly failure injection is limited to recorded local execution.")

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
            textract_timeout_seconds=_environment_integer(
                values, "CLAIMS_TEXTRACT_TIMEOUT_SECONDS"
            ),
            textract_concurrency_limit=_environment_integer(
                values, "CLAIMS_TEXTRACT_CONCURRENCY_LIMIT"
            ),
            bedrock_region=_environment_value(values, "CLAIMS_BEDROCK_REGION"),
            bedrock_model_id=_environment_value(values, "CLAIMS_BEDROCK_MODEL_ID"),
            bedrock_timeout_seconds=_environment_integer(values, "CLAIMS_BEDROCK_TIMEOUT_SECONDS"),
            bedrock_concurrency_limit=_environment_integer(
                values, "CLAIMS_BEDROCK_CONCURRENCY_LIMIT"
            ),
            provider_max_attempts=_environment_bounded_integer(
                values,
                "CLAIMS_PROVIDER_MAX_ATTEMPTS",
                maximum=3,
            ),
            retry_base_seconds=_environment_integer(values, "CLAIMS_RETRY_BASE_SECONDS"),
            retry_max_seconds=_environment_integer(values, "CLAIMS_RETRY_MAX_SECONDS"),
            retry_jitter_ratio=_environment_ratio(values, "CLAIMS_RETRY_JITTER_RATIO"),
            observability_enabled=_environment_boolean(values, "CLAIMS_OBSERVABILITY_ENABLED"),
            phoenix_endpoint=_environment_value(values, "CLAIMS_PHOENIX_ENDPOINT"),
            phoenix_project=_environment_value(values, "CLAIMS_PHOENIX_PROJECT"),
            log_root=Path(_environment_value(values, "CLAIMS_LOG_ROOT")),
            log_max_bytes=_environment_integer(values, "CLAIMS_LOG_MAX_BYTES"),
            log_backup_count=_environment_integer(values, "CLAIMS_LOG_BACKUP_COUNT"),
            execution_profile=resolve_execution_profile(
                _environment_value(values, "CLAIMS_EXECUTION_PROFILE"),
                run_live_aws=_environment_boolean(values, "CLAIMS_RUN_LIVE_AWS"),
            ),
            run_live_aws=_environment_boolean(values, "CLAIMS_RUN_LIVE_AWS"),
            worker_id=_environment_value(values, "CLAIMS_WORKER_ID"),
            worker_poll_seconds=_environment_integer(values, "CLAIMS_WORKER_POLL_SECONDS"),
            worker_lease_seconds=_environment_integer(values, "CLAIMS_WORKER_LEASE_SECONDS"),
            worker_shutdown_seconds=_environment_integer(
                values,
                "CLAIMS_WORKER_SHUTDOWN_SECONDS",
            ),
            inject_anomaly_enrichment_failure=_environment_boolean(
                values, "CLAIMS_INJECT_ANOMALY_ENRICHMENT_FAILURE"
            ),
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


def _environment_bounded_integer(
    values: Mapping[str, str | None],
    name: str,
    *,
    maximum: int,
) -> int:
    value = _environment_integer(values, name)
    if value > maximum:
        raise ConfigurationError(f"{name} cannot exceed {maximum}")
    return value


def _environment_ratio(values: Mapping[str, str | None], name: str) -> float:
    raw = _environment_value(values, name)
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a number") from error
    if not 0 <= value <= 1:
        raise ConfigurationError(f"{name} must be between 0 and 1")
    return value


def _environment_boolean(values: Mapping[str, str | None], name: str) -> bool:
    raw = _environment_value(values, name)
    if raw not in {"0", "1"}:
        raise ConfigurationError(f"{name} must be 0 or 1")
    return raw == "1"
