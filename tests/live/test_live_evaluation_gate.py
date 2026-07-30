"""Generate a non-gating twelve-case report using live OCR and model providers.

This is intentionally separate from the recorded rendered gate. Live provider
variability must be reported per case rather than turning a deterministic test
into a flaky CI assertion.
"""

import asyncio
import json
from datetime import UTC, datetime
from hashlib import sha256
from os import environ
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.reconstruction import PostgresClaimReconstructor
from claims_backend.observability import ObservabilityConfig, create_observability
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.runtime.profiles import ExecutionProfile
from claims_backend.worker.application import create_claim_worker
from evaluation_workbench import (
    ActualCaseResult,
    EvaluationRunBuilder,
    OracleScorer,
    OutcomeSnapshot,
    SourceVersions,
    load_evaluation_inputs,
)
from evaluation_workbench.models import ExecutionProfile as EvalExecutionProfile
from tests.integration.test_rendered_evaluation_gate import (
    _DATASET_PATH,
    _OVERLAY_BYTES,
    _POLICY_BYTES,
    _RAW_DATASET,
    _actual_result,
    _render_documents,
    _submit_claim,
)
from tests.integration.test_rendered_evaluation_gate import (
    _import_evaluation_facts as _import_recorded_facts,
)

pytestmark = [
    pytest.mark.live_aws,
    pytest.mark.skipif(
        environ.get("CLAIMS_RUN_LIVE_AWS") != "1",
        reason="Set CLAIMS_RUN_LIVE_AWS=1 to run the live twelve-case evaluation.",
    ),
]

_ARTIFACT_PATH = Path("artifacts/backend-v1/live-12-evaluation-report.json")


@pytest.mark.asyncio
async def test_all_twelve_cases_generate_live_evaluation_report(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    """Run every assignment case with real AWS and record pass/fail, never hide failures."""
    settings = Settings.from_env()
    if settings.execution_profile is not ExecutionProfile.LIVE_INTELLIGENCE:
        settings = Settings(
            database_url=migrated_database_url,
            data_root=tmp_path / "documents",
            log_root=tmp_path / "logs",
            execution_profile=ExecutionProfile.LIVE_INTELLIGENCE,
            run_live_aws=True,
            aws_region=settings.aws_region,
            bedrock_region=settings.bedrock_region,
            bedrock_model_id=settings.bedrock_model_id,
            observability_enabled=True,
            phoenix_endpoint=settings.phoenix_endpoint,
            phoenix_project=settings.phoenix_project,
        )
    else:
        settings = Settings(
            database_url=migrated_database_url,
            data_root=tmp_path / "documents",
            log_root=tmp_path / "logs",
            execution_profile=settings.execution_profile,
            run_live_aws=settings.run_live_aws,
            aws_region=settings.aws_region,
            bedrock_region=settings.bedrock_region,
            bedrock_model_id=settings.bedrock_model_id,
            bedrock_timeout_seconds=settings.bedrock_timeout_seconds,
            bedrock_concurrency_limit=settings.bedrock_concurrency_limit,
            textract_timeout_seconds=settings.textract_timeout_seconds,
            textract_concurrency_limit=settings.textract_concurrency_limit,
            observability_enabled=True,
            phoenix_endpoint=settings.phoenix_endpoint,
            phoenix_project=settings.phoenix_project,
        )

    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_recorded_facts(factory, _RAW_DATASET)
    exporter = InMemorySpanExporter()
    api_observability = create_observability(
        ObservabilityConfig(log_root=settings.log_root),
        process_name="api",
        span_exporter=exporter,
    )
    worker_observability = create_observability(
        ObservabilityConfig(log_root=settings.log_root),
        process_name="worker",
        span_exporter=exporter,
    )
    app = create_app(settings, observability=api_observability)
    runtime = create_process_runtime(
        settings,
        process_name="worker",
        observability=worker_observability,
    )
    worker = create_claim_worker(runtime)
    reconstructor = PostgresClaimReconstructor(factory)
    dataset = load_evaluation_inputs(_DATASET_PATH)
    builder = EvaluationRunBuilder(dataset, _live_source_versions(settings))
    case_records: list[dict[str, object]] = []

    try:
        await worker.setup()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            for raw_case in _RAW_DATASET["test_cases"]:
                case_id = str(raw_case["case_id"])
                started = monotonic()
                claim_id: UUID | None = None
                error: Exception | None = None
                try:
                    claim_id = await _submit_claim(
                        client,
                        raw_case,
                        _render_documents(raw_case["input"]),
                        idempotency_suffix="live-12-gate",
                    )
                    await worker.run_once()
                    projection = await client.get(
                        f"/v1/claims/{claim_id}",
                        headers={
                            "X-Dev-Username": (
                                f"member.{str(raw_case['input']['member_id']).casefold()}"
                            )
                        },
                    )
                    if projection.status_code != 200:
                        raise RuntimeError(
                            f"claim projection returned HTTP {projection.status_code}"
                        )
                    reconstruction = await reconstructor.reconstruct(claim_id)
                    if reconstruction is None:
                        raise RuntimeError("claim reconstruction returned no record")
                    actual = _actual_result(case_id, raw_case, reconstruction)
                except Exception as caught:
                    error = caught
                    actual = _failed_actual(raw_case, caught)
                builder.record(actual)
                spans = _spans_for_claim(exporter, claim_id)
                case_records.append(
                    {
                        "case_id": case_id,
                        "claim_id": None if claim_id is None else str(claim_id),
                        "duration_seconds": round(monotonic() - started, 2),
                        "error": None if error is None else f"{type(error).__name__}: {error}",
                        "actual": actual.model_dump(mode="json"),
                        "trace": {
                            "span_count": len(spans),
                            "span_names": sorted({span.name for span in spans}),
                            "trace_ids": sorted(
                                {
                                    f"{span.context.trace_id:032x}"
                                    for span in spans
                                    if span.context.is_valid
                                }
                            ),
                        },
                    }
                )
    finally:
        await worker.close()
        api_observability.shutdown()
        worker_observability.shutdown()
        await app.state.engine.dispose()
        await engine.dispose()

    report = OracleScorer.score(_DATASET_PATH, builder.finalize())
    payload = {
        "artifact_schema": "claims-live-12-evaluation-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "command": (
            "CLAIMS_RUN_LIVE_AWS=1 CLAIMS_EXECUTION_PROFILE=LIVE_INTELLIGENCE "
            "uv run pytest tests/live/test_live_evaluation_gate.py -q"
        ),
        "provider_mode": "LIVE_INTELLIGENCE",
        "providers": ["AMAZON_TEXTRACT", "AMAZON_BEDROCK"],
        "model_id": settings.bedrock_model_id,
        "case_count": len(report.cases),
        "passed": report.passed,
        "passed_case_count": sum(case.passed for case in report.cases),
        "failed_case_count": sum(not case.passed for case in report.cases),
        "cases": [case.model_dump(mode="json") for case in report.cases],
        "execution": case_records,
        "limitations": [
            "Live providers may produce variable output and safe failures.",
            "Inputs are synthetic assignment documents; no production PHI was used.",
            "This report is not the deterministic recorded acceptance gate.",
        ],
    }
    await asyncio.to_thread(_ARTIFACT_PATH.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        _ARTIFACT_PATH.write_text,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    assert len(report.cases) == 12
    assert await asyncio.to_thread(_ARTIFACT_PATH.is_file)


def _live_source_versions(settings: Settings) -> SourceVersions:
    return SourceVersions(
        dataset_version=str(_RAW_DATASET["version"]),
        dataset_sha256=sha256(Path("problem_statement/test_cases.json").read_bytes()).hexdigest(),
        policy_version="PLUM_GHI_2024:1",
        policy_sha256=sha256(_POLICY_BYTES).hexdigest(),
        overlay_version="assignment-overlay:2",
        overlay_sha256=sha256(_OVERLAY_BYTES).hexdigest(),
        model_id=settings.bedrock_model_id,
        prompt_versions=("fast-triage-prompt-v3", "complex-extraction-prompt-v4"),
        schema_versions=("triage-provider-output-v4", "complex-extraction-v1"),
        graph_version="claim-processing-v7",
        execution_profile=EvalExecutionProfile.LIVE_INTELLIGENCE,
        ocr_mode="ENABLED",
    )


def _failed_actual(raw_case: dict[str, Any], error: Exception) -> ActualCaseResult:
    inputs = raw_case["input"]
    return ActualCaseResult(
        case_id=str(raw_case["case_id"]),
        outcome=OutcomeSnapshot(
            lifecycle="PROCESSING_FAILED",
            adjudication=None,
            approved_paise=None,
            reason_codes=(type(error).__name__,),
            provenance=tuple(str(item["file_id"]) for item in inputs["documents"]),
            trace_complete=False,
            assumptions=(),
            failures=(type(error).__name__,),
        ),
    )


def _spans_for_claim(exporter: InMemorySpanExporter, claim_id: UUID | None) -> list[Any]:
    if claim_id is None:
        return []
    value = str(claim_id)
    return [
        span
        for span in exporter.get_finished_spans()
        if str((span.attributes or {}).get("claim.id")) == value
        or str((span.attributes or {}).get("session.id")) == value
    ]
