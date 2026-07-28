from pathlib import Path

import pytest

from claims_backend.config import ConfigurationError, Settings

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
    "CLAIMS_BEDROCK_REGION": "us-west-2",
    "CLAIMS_BEDROCK_MODEL_ID": "qwen.test-model-v1:0",
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
    assert settings.bedrock_region == "us-west-2"
    assert settings.bedrock_model_id == "qwen.test-model-v1:0"


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
