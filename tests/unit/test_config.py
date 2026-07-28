from pathlib import Path

import pytest

from claims_backend.config import ConfigurationError, Settings
from claims_backend.runtime.profiles import ExecutionProfile, ProfileAuthorizationError

_ENVIRONMENT = {
    "CLAIMS_DATABASE_URL": "postgresql+psycopg://local/test",
    "CLAIMS_DATA_ROOT": "local-data",
    "CLAIMS_MAX_DOCUMENTS": "7",
    "CLAIMS_MAX_FILE_BYTES": "1000",
    "CLAIMS_MAX_CLAIM_BYTES": "2000",
    "CLAIMS_MAX_DOCUMENT_PAGES": "8",
    "CLAIMS_UPLOAD_CHUNK_BYTES": "100",
    "CLAIMS_MAX_TEXTRACT_PAGE_BYTES": "500",
    "CLAIMS_PAGE_RENDER_DPI": "144",
    "CLAIMS_AWS_REGION": "ap-southeast-2",
    "CLAIMS_TEXTRACT_TIMEOUT_SECONDS": "31",
    "CLAIMS_TEXTRACT_CONCURRENCY_LIMIT": "3",
    "CLAIMS_BEDROCK_REGION": "us-west-2",
    "CLAIMS_BEDROCK_MODEL_ID": "qwen.test-model-v1:0",
    "CLAIMS_BEDROCK_TIMEOUT_SECONDS": "91",
    "CLAIMS_BEDROCK_CONCURRENCY_LIMIT": "4",
    "CLAIMS_PROVIDER_MAX_ATTEMPTS": "3",
    "CLAIMS_RETRY_BASE_SECONDS": "2",
    "CLAIMS_RETRY_MAX_SECONDS": "40",
    "CLAIMS_RETRY_JITTER_RATIO": "0.2",
    "CLAIMS_OBSERVABILITY_ENABLED": "1",
    "CLAIMS_PHOENIX_ENDPOINT": "http://127.0.0.1:6006/v1/traces",
    "CLAIMS_PHOENIX_PROJECT": "claims-test",
    "CLAIMS_LOG_ROOT": "local-logs",
    "CLAIMS_LOG_MAX_BYTES": "4096",
    "CLAIMS_LOG_BACKUP_COUNT": "3",
    "CLAIMS_EXECUTION_PROFILE": "LOCAL",
    "CLAIMS_RUN_LIVE_AWS": "0",
    "CLAIMS_WORKER_ID": "config-test-worker",
    "CLAIMS_WORKER_POLL_SECONDS": "3",
    "CLAIMS_WORKER_LEASE_SECONDS": "301",
    "CLAIMS_WORKER_SHUTDOWN_SECONDS": "121",
    "CLAIMS_OBSERVABILITY_CAPTURE_CONTENT": "0",
    "CLAIMS_OBSERVABILITY_SYNTHETIC_ONLY": "0",
    "CLAIMS_INJECT_ANOMALY_ENRICHMENT_FAILURE": "0",
}


def test_settings_load_every_runtime_value_from_explicit_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    env_file = _write_env(tmp_path, _ENVIRONMENT)

    settings = Settings.from_env(env_file)

    assert settings.database_url == "postgresql+psycopg://local/test"
    assert settings.data_root == Path("local-data")
    assert settings.max_documents == 7
    assert settings.max_file_bytes == 1000
    assert settings.max_claim_bytes == 2000
    assert settings.max_document_pages == 8
    assert settings.upload_chunk_bytes == 100
    assert settings.max_textract_page_bytes == 500
    assert settings.page_render_dpi == 144
    assert settings.aws_region == "ap-southeast-2"
    assert settings.textract_timeout_seconds == 31
    assert settings.textract_concurrency_limit == 3
    assert settings.bedrock_region == "us-west-2"
    assert settings.bedrock_model_id == "qwen.test-model-v1:0"
    assert settings.bedrock_timeout_seconds == 91
    assert settings.bedrock_concurrency_limit == 4
    assert settings.provider_max_attempts == 3
    assert settings.retry_base_seconds == 2
    assert settings.retry_max_seconds == 40
    assert settings.retry_jitter_ratio == 0.2
    assert settings.observability_enabled is True
    assert settings.phoenix_endpoint == "http://127.0.0.1:6006/v1/traces"
    assert settings.phoenix_project == "claims-test"
    assert settings.log_root == Path("local-logs")
    assert settings.log_max_bytes == 4096
    assert settings.log_backup_count == 3
    assert settings.execution_profile is ExecutionProfile.RECORDED_LOCAL
    assert settings.run_live_aws is False
    assert settings.worker_id == "config-test-worker"
    assert settings.worker_poll_seconds == 3
    assert settings.worker_lease_seconds == 301
    assert settings.worker_shutdown_seconds == 121
    assert settings.observability_capture_content is False
    assert settings.observability_synthetic_only is False
    assert settings.inject_anomaly_enrichment_failure is False


def test_process_environment_overrides_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    env_file = _write_env(tmp_path, _ENVIRONMENT)
    monkeypatch.setenv("CLAIMS_BEDROCK_REGION", "us-east-2")

    settings = Settings.from_env(env_file)

    assert settings.bedrock_region == "us-east-2"


def test_missing_or_invalid_configuration_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    empty_file = _write_env(tmp_path, {})
    with pytest.raises(ConfigurationError, match="Missing required configuration"):
        Settings.from_env(empty_file)

    invalid = {**_ENVIRONMENT, "CLAIMS_MAX_DOCUMENTS": "many"}
    invalid_file = _write_env(tmp_path, invalid)
    with pytest.raises(ConfigurationError, match="CLAIMS_MAX_DOCUMENTS must be an integer"):
        Settings.from_env(invalid_file)

    invalid_ratio = {**_ENVIRONMENT, "CLAIMS_RETRY_JITTER_RATIO": "1.1"}
    invalid_ratio_file = _write_env(tmp_path, invalid_ratio)
    with pytest.raises(
        ConfigurationError,
        match="CLAIMS_RETRY_JITTER_RATIO must be between 0 and 1",
    ):
        Settings.from_env(invalid_ratio_file)

    invalid_boolean = {**_ENVIRONMENT, "CLAIMS_OBSERVABILITY_ENABLED": "sometimes"}
    invalid_boolean_file = _write_env(tmp_path, invalid_boolean)
    with pytest.raises(
        ConfigurationError,
        match="CLAIMS_OBSERVABILITY_ENABLED must be 0 or 1",
    ):
        Settings.from_env(invalid_boolean_file)


def test_live_profile_requires_explicit_paid_aws_authorization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    live = {
        **_ENVIRONMENT,
        "CLAIMS_EXECUTION_PROFILE": "LIVE_INTELLIGENCE",
        "CLAIMS_RUN_LIVE_AWS": "0",
    }

    with pytest.raises(ProfileAuthorizationError, match="CLAIMS_RUN_LIVE_AWS=1"):
        Settings.from_env(_write_env(tmp_path, live))

    live["CLAIMS_RUN_LIVE_AWS"] = "1"
    settings = Settings.from_env(_write_env(tmp_path, live))

    assert settings.execution_profile is ExecutionProfile.LIVE_INTELLIGENCE
    assert settings.run_live_aws is True


def test_paid_aws_authorization_does_not_enable_live_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    recorded = {**_ENVIRONMENT, "CLAIMS_RUN_LIVE_AWS": "1"}

    settings = Settings.from_env(_write_env(tmp_path, recorded))

    assert settings.execution_profile is ExecutionProfile.RECORDED_LOCAL
    assert settings.run_live_aws is True


def test_anomaly_failure_injection_is_limited_to_recorded_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_configuration(monkeypatch)
    recorded = {**_ENVIRONMENT, "CLAIMS_INJECT_ANOMALY_ENRICHMENT_FAILURE": "1"}
    assert Settings.from_env(_write_env(tmp_path, recorded)).inject_anomaly_enrichment_failure

    live = {
        **recorded,
        "CLAIMS_EXECUTION_PROFILE": "LIVE_INTELLIGENCE",
        "CLAIMS_RUN_LIVE_AWS": "1",
    }
    with pytest.raises(ValueError, match="limited to recorded local"):
        Settings.from_env(_write_env(tmp_path, live))


def _clear_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def _write_env(tmp_path: Path, values: dict[str, str]) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )
    return path
