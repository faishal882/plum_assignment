from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claims_backend.config import Settings
from claims_backend.observability import ObservabilityConfig, create_observability
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.runtime.profiles import ExecutionProfile


@pytest.mark.asyncio
async def test_process_runtime_constructs_local_dependencies_without_provider_calls(
    tmp_path: Path,
) -> None:
    runtime = create_process_runtime(
        Settings(
            database_url="postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
            data_root=tmp_path,
            execution_profile=ExecutionProfile.RECORDED_LOCAL,
        ),
        process_name="worker",
    )

    assert runtime.profile is ExecutionProfile.RECORDED_LOCAL
    assert runtime.session_factory is not None
    assert runtime.observability is None

    await runtime.close()


@pytest.mark.asyncio
async def test_process_runtime_preserves_injected_observability(tmp_path: Path) -> None:
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=InMemorySpanExporter(),
    )
    runtime = create_process_runtime(
        Settings(
            database_url="postgresql+psycopg://claims:claims@127.0.0.1:55432/claims",
            data_root=tmp_path,
        ),
        process_name="worker",
        observability=observability,
    )

    assert runtime.observability is observability

    await runtime.close()
    observability.shutdown()
