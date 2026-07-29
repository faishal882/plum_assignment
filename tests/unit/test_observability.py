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


def test_errors_record_complete_exception_details_for_debugging(tmp_path: Path) -> None:
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
    assert span.attributes["error.message"] == "Kavita Nair diagnosis must never enter telemetry"
    serialized = json.dumps(dict(span.attributes))
    assert "Kavita Nair" in serialized
    assert "diagnosis" in serialized.casefold()


def test_later_operation_can_attach_to_persisted_trace_context(
    tmp_path: Path,
) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="api",
        span_exporter=exporter,
    )

    with observability.span("claim.workflow.node", component="workflow") as parent:
        trace_id = f"{parent.context.trace_id:032x}"
        span_id = f"{parent.context.span_id:016x}"
    with observability.span(
        "review.resolve",
        component="review",
        parent_trace_id=trace_id,
        parent_span_id=span_id,
    ):
        pass

    observability.shutdown()
    parent_span, review_span = exporter.get_finished_spans()
    assert review_span.context.trace_id == parent_span.context.trace_id
    assert review_span.parent is not None
    assert review_span.parent.span_id == parent_span.context.span_id


def test_runtime_tracing_allows_unredacted_keys_and_values(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="evaluation",
        span_exporter=exporter,
    )

    with observability.span(
        "debug",
        component="evaluation",
        attributes={
            "patient_name": "Kavita Nair",
            "ocr_text": "Diagnosis: Chronic Joint Pain",
        },
    ):
        observability.log(
            EngineeringLogEvent(
                event_name="debug",
                component="evaluation",
                outcome="Kavita Nair",
            )
        )
    observability.shutdown()

    span = exporter.get_finished_spans()[0]
    assert span.attributes["patient_name"] == "Kavita Nair"
    assert span.attributes["ocr_text"] == "Diagnosis: Chronic Joint Pain"
    record = json.loads((tmp_path / "evaluation.jsonl").read_text().strip())
    assert record["outcome"] == "Kavita Nair"


def test_telemetry_scanner_detects_canaries_in_exported_data() -> None:
    with pytest.raises(PrivacyViolation, match="PHI canary"):
        scan_telemetry_for_phi(
            [{"claim.id": "Kavita Nair"}],
            phi_canaries=("Kavita Nair",),
        )


def test_observability_has_no_content_capture_profile_gate(tmp_path: Path) -> None:
    assert ObservabilityConfig(log_root=tmp_path).log_root == tmp_path
