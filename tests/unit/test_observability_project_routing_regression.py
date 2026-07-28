from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claims_backend.observability import ObservabilityConfig, create_observability


def test_phoenix_project_uses_openinference_resource_attribute(tmp_path) -> None:
    # Regression: ISSUE-001 — Phoenix ignored the obsolete phoenix.project.name key.
    # Found by /qa on 2026-07-29
    # Report: .gstack/qa-reports/qa-report-localhost-2026-07-29.md
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(
            log_root=tmp_path,
            project_name="plum-claims-regression",
        ),
        process_name="api",
        span_exporter=exporter,
    )

    with observability.span("api.request", component="api"):
        pass
    observability.shutdown()

    span = exporter.get_finished_spans()[0]
    assert span.resource.attributes["openinference.project.name"] == "plum-claims-regression"
    assert "phoenix.project.name" not in span.resource.attributes
