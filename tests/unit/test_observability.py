import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from claims_backend.observability import (
    EngineeringLogEvent,
    ObservabilityConfig,
    PrivacyViolation,
    create_observability,
    scan_telemetry_for_phi,
)


def test_span_and_jsonl_log_share_safe_trace_correlation(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=exporter,
    )

    with observability.span(
        "claim.workflow",
        component="workflow",
        attributes={
            "claim.id": "00000000-0000-0000-0000-000000000001",
            "claim.version": 1,
            "workflow.run_id": "00000000-0000-0000-0000-000000000002",
            "work.attempt": 1,
        },
    ):
        observability.log(
            EngineeringLogEvent(
                event_name="workflow_started",
                component="workflow",
                claim_id="00000000-0000-0000-0000-000000000001",
                workflow_run_id="00000000-0000-0000-0000-000000000002",
                attempt=1,
                duration_ms=0,
                outcome="RUNNING",
            )
        )

    observability.shutdown()
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "claim.workflow"
    assert spans[0].attributes["outcome"] == "OK"
    assert spans[0].attributes["duration_ms"] >= 0

    record = json.loads((tmp_path / "worker.jsonl").read_text().strip())
    assert record["process"] == "worker"
    assert record["trace_id"] == f"{spans[0].context.trace_id:032x}"
    assert record["span_id"] == f"{spans[0].context.span_id:016x}"
    assert record["claim_id"] == "00000000-0000-0000-0000-000000000001"
    assert record["workflow_run_id"] == "00000000-0000-0000-0000-000000000002"
    assert record["attempt"] == 1
    assert record["outcome"] == "RUNNING"


def test_errors_record_only_sanitized_exception_class(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=exporter,
    )

    with pytest.raises(RuntimeError, match="Kavita Nair"):
        with observability.span("claim.workflow.node", component="policy"):
            raise RuntimeError("Kavita Nair diagnosis must never enter telemetry")

    observability.shutdown()
    span = exporter.get_finished_spans()[0]
    assert span.attributes["outcome"] == "ERROR"
    assert span.attributes["error.type"] == "RuntimeError"
    serialized = json.dumps(dict(span.attributes))
    assert "Kavita Nair" not in serialized
    assert "diagnosis" not in serialized.casefold()


def test_phi_canary_rejects_forbidden_keys_and_values(tmp_path: Path) -> None:
    observability = create_observability(
        ObservabilityConfig(
            log_root=tmp_path,
            phi_canaries=("Kavita Nair", "Chronic Joint Pain"),
        ),
        process_name="evaluation",
    )

    with pytest.raises(PrivacyViolation, match="forbidden attribute key"):
        with observability.span(
            "unsafe",
            component="evaluation",
            attributes={"patient_name": "redacted"},
        ):
            pass
    with pytest.raises(PrivacyViolation, match="PHI canary"):
        observability.log(
            EngineeringLogEvent(
                event_name="unsafe",
                component="evaluation",
                outcome="Kavita Nair",
            )
        )


def test_telemetry_scanner_detects_canaries_in_exported_data() -> None:
    with pytest.raises(PrivacyViolation, match="PHI canary"):
        scan_telemetry_for_phi(
            [{"claim.id": "Kavita Nair"}],
            phi_canaries=("Kavita Nair",),
        )


def test_rich_content_capture_requires_explicit_synthetic_profile(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="synthetic-only"):
        ObservabilityConfig(
            log_root=tmp_path,
            capture_content=True,
            execution_profile="LOCAL",
        )

    config = ObservabilityConfig(
        log_root=tmp_path,
        capture_content=True,
        execution_profile="LIVE_INTELLIGENCE",
        synthetic_only=True,
    )
    assert config.capture_content is True
