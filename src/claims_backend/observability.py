import json
import logging
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import monotonic
from typing import cast

from openinference.semconv.resource import ResourceAttributes
from openinference.semconv.trace import (
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    Tracer,
    set_span_in_context,
)
from opentelemetry.util.types import AttributeValue

_SAFE_ATTRIBUTE_PREFIXES = (
    "api.",
    "casefile.",
    "claim.",
    "component",
    "duration_ms",
    "error.",
    "evaluation.",
    "http.",
    "llm.token_count.",
    "model.",
    "node.",
    "openinference.",
    "outcome",
    "persistence.",
    "policy.",
    "provider.",
    "reconciliation.",
    "review.",
    "service.",
    "textract.",
    "work.",
    "workflow.",
)
_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "credential",
    "diagnosis",
    "document_bytes",
    "local_path",
    "ocr_text",
    "patient_name",
    "raw_prompt",
    "raw_response",
    "secret",
)
_RICH_CONTENT_KEYS = {
    SpanAttributes.INPUT_VALUE,
    SpanAttributes.OUTPUT_VALUE,
}
_PROCESS_NAMES = frozenset({"api", "worker", "evaluation"})


class PrivacyViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    log_root: Path
    enabled: bool = True
    phoenix_endpoint: str | None = None
    project_name: str = "plum-claims-local"
    service_version: str = "0.1.0"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    execution_profile: str = "LOCAL"
    capture_content: bool = False
    synthetic_only: bool = False
    phi_canaries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.log_max_bytes <= 0:
            raise ValueError("log_max_bytes must be positive")
        if self.log_backup_count <= 0:
            raise ValueError("log_backup_count must be positive")
        if not self.project_name:
            raise ValueError("project_name cannot be empty")
        if self.capture_content and (
            self.execution_profile != "LIVE_INTELLIGENCE" or not self.synthetic_only
        ):
            raise ValueError(
                "Rich content capture requires an explicit synthetic-only "
                "LIVE_INTELLIGENCE profile."
            )


@dataclass(frozen=True, slots=True)
class EngineeringLogEvent:
    event_name: str
    component: str
    outcome: str
    claim_id: str | None = None
    workflow_run_id: str | None = None
    attempt: int | None = None
    duration_ms: int | None = None
    severity: str = "INFO"
    provider_name: str | None = None
    provider_request_id: str | None = None
    error_type: str | None = None


class PrivacyGuard:
    def __init__(
        self,
        *,
        phi_canaries: Sequence[str] = (),
        allow_rich_content: bool = False,
    ) -> None:
        self._canaries = tuple(value.casefold() for value in phi_canaries if value)
        self._allow_rich_content = allow_rich_content

    def attributes(
        self,
        attributes: Mapping[str, AttributeValue],
    ) -> dict[str, AttributeValue]:
        for key, value in attributes.items():
            normalized_key = key.casefold()
            if any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
                raise PrivacyViolation(f"Telemetry contains forbidden attribute key: {key}")
            if not any(normalized_key.startswith(prefix) for prefix in _SAFE_ATTRIBUTE_PREFIXES):
                if not (self._allow_rich_content and key in _RICH_CONTENT_KEYS):
                    raise PrivacyViolation(f"Telemetry contains forbidden attribute key: {key}")
            self._value(value)
        return dict(attributes)

    def payload(self, payload: Mapping[str, object]) -> None:
        _scan_value(payload, self._canaries)

    def _value(self, value: AttributeValue) -> None:
        _scan_value(value, self._canaries)


class Observability:
    def __init__(
        self,
        *,
        tracer_provider: TracerProvider,
        tracer: Tracer,
        process_name: str,
        guard: PrivacyGuard,
        logger: logging.Logger,
        handler: logging.Handler,
    ) -> None:
        self._tracer_provider = tracer_provider
        self._tracer = tracer
        self._process_name = process_name
        self._guard = guard
        self._logger = logger
        self._handler = handler

    @contextmanager
    def span(
        self,
        name: str,
        *,
        component: str,
        attributes: Mapping[str, AttributeValue] | None = None,
        span_kind: str = OpenInferenceSpanKindValues.CHAIN.value,
        parent_trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Iterator[Span]:
        safe_attributes: dict[str, AttributeValue] = {
            "component": component,
            SpanAttributes.OPENINFERENCE_SPAN_KIND: span_kind,
            **(attributes or {}),
        }
        safe_attributes = self._guard.attributes(safe_attributes)
        started = monotonic()
        failed_error: Exception | None = None
        parent_context = _parent_context(parent_trace_id, parent_span_id)
        with self._tracer.start_as_current_span(
            name,
            context=parent_context,
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield cast(Span, span)
            except Exception as error:
                failed_error = error
                span.set_attribute("error.type", type(error).__name__)
                span.set_attribute("outcome", "ERROR")
                span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                duration_ms = max(0, round((monotonic() - started) * 1000))
                span.set_attribute("duration_ms", duration_ms)
                if failed_error is None:
                    span.set_attribute("outcome", "OK")
                    span.set_status(Status(StatusCode.OK))

    def set_attributes(
        self,
        span: Span,
        attributes: Mapping[str, AttributeValue],
    ) -> None:
        for key, value in self._guard.attributes(attributes).items():
            span.set_attribute(key, value)

    def log(self, event: EngineeringLogEvent) -> None:
        span_context = trace.get_current_span().get_span_context()
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": event.severity,
            "process": self._process_name,
            "component": event.component,
            "event": event.event_name,
            "claim_id": event.claim_id,
            "workflow_run_id": event.workflow_run_id,
            "trace_id": (
                f"{span_context.trace_id:032x}" if span_context.is_valid else None
            ),
            "span_id": (
                f"{span_context.span_id:016x}" if span_context.is_valid else None
            ),
            "attempt": event.attempt,
            "duration_ms": event.duration_ms,
            "outcome": event.outcome,
            "provider_name": event.provider_name,
            "provider_request_id": event.provider_request_id,
            "error_type": event.error_type,
        }
        self._guard.payload(payload)
        record = self._logger.makeRecord(
            self._logger.name,
            getattr(logging, event.severity, logging.INFO),
            "",
            0,
            "",
            (),
            None,
            extra={"structured_event": payload},
        )
        self._logger.handle(record)

    def shutdown(self) -> None:
        self._handler.flush()
        self._handler.close()
        self._tracer_provider.shutdown()


def create_observability(
    config: ObservabilityConfig,
    *,
    process_name: str,
    span_exporter: SpanExporter | None = None,
) -> Observability:
    if process_name not in _PROCESS_NAMES:
        raise ValueError(f"Unsupported process name: {process_name}")
    resource = Resource.create(
        {
            "service.name": f"plum-claims-{process_name}",
            "service.version": config.service_version,
            ResourceAttributes.PROJECT_NAME: config.project_name,
        }
    )
    provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif config.enabled and config.phoenix_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=config.phoenix_endpoint))
        )
    tracer = provider.get_tracer("claims_backend", config.service_version)
    guard = PrivacyGuard(
        phi_canaries=config.phi_canaries,
        allow_rich_content=config.capture_content,
    )
    logger, handler = _engineering_logger(config, process_name)
    return Observability(
        tracer_provider=provider,
        tracer=tracer,
        process_name=process_name,
        guard=guard,
        logger=logger,
        handler=handler,
    )


def scan_telemetry_for_phi(
    records: Sequence[Mapping[str, object]],
    *,
    phi_canaries: Sequence[str],
) -> None:
    canaries = tuple(value.casefold() for value in phi_canaries if value)
    for record in records:
        _scan_value(record, canaries)


def trace_identifiers() -> tuple[str | None, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def _parent_context(
    trace_id: str | None,
    span_id: str | None,
) -> context.Context | None:
    if trace_id is None and span_id is None:
        return None
    if trace_id is None or span_id is None:
        raise ValueError("Both parent trace and span identifiers are required")
    if len(trace_id) != 32 or len(span_id) != 16:
        raise ValueError("Parent trace identifiers have invalid lengths")
    try:
        parsed_trace_id = int(trace_id, 16)
        parsed_span_id = int(span_id, 16)
    except ValueError as error:
        raise ValueError("Parent trace identifiers must be hexadecimal") from error
    parent = SpanContext(
        trace_id=parsed_trace_id,
        span_id=parsed_span_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    if not parent.is_valid:
        raise ValueError("Parent trace identifiers are invalid")
    return set_span_in_context(NonRecordingSpan(parent))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "structured_event", None)
        if not isinstance(payload, dict):
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": "ERROR",
                "process": "unknown",
                "component": "logging",
                "event": "unstructured_log_rejected",
                "outcome": "ERROR",
            }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class _SafeRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        sys.stderr.write("claims engineering log write failed\n")


def _engineering_logger(
    config: ObservabilityConfig,
    process_name: str,
) -> tuple[logging.Logger, logging.Handler]:
    config.log_root.mkdir(parents=True, exist_ok=True)
    path = config.log_root / f"{process_name}.jsonl"
    handler = _SafeRotatingFileHandler(
        path,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(_JsonFormatter())
    logger = logging.Logger(f"claims.engineering.{process_name}.{id(handler)}", logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return logger, handler


def _scan_value(value: object, canaries: Sequence[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if any(part in normalized_key for part in _FORBIDDEN_KEY_PARTS):
                raise PrivacyViolation(
                    f"Telemetry contains forbidden attribute key: {key}"
                )
            _scan_value(child, canaries)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for child in value:
            _scan_value(child, canaries)
        return
    if isinstance(value, str):
        normalized = value.casefold()
        if any(canary in normalized for canary in canaries):
            raise PrivacyViolation("Telemetry contains a configured PHI canary.")
