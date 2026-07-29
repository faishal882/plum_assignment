import base64
import json
from collections.abc import Mapping
from threading import BoundedSemaphore
from time import monotonic
from typing import cast

from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from langchain_aws import ChatBedrockConverse
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.util.types import AttributeValue
from pydantic import BaseModel, ValidationError

from claims_backend.config import Settings
from claims_backend.domain.extraction import ModelProviderError, ModelSchemaValidationError
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation
from claims_backend.observability import EngineeringLogEvent, Observability


class ChatBedrockConverseTransport:
    def __init__(
        self,
        *,
        connect_timeout_seconds: int = 30,
        read_timeout_seconds: int = 90,
        concurrency_limit: int = 2,
        observability: Observability | None = None,
    ) -> None:
        for name, value in (
            ("connect_timeout_seconds", connect_timeout_seconds),
            ("read_timeout_seconds", read_timeout_seconds),
            ("concurrency_limit", concurrency_limit),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._permit = BoundedSemaphore(concurrency_limit)
        self._observability = observability

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        observability: Observability | None = None,
    ) -> "ChatBedrockConverseTransport":
        return cls(
            read_timeout_seconds=settings.bedrock_timeout_seconds,
            concurrency_limit=settings.bedrock_concurrency_limit,
            observability=observability,
        )

    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        if self._observability is None:
            return self._invoke(config, schema, messages)
        input_payload = {
            "messages": [
                {
                    "role": role,
                    "content": content,
                }
                for role, content in messages
            ],
            "response_schema": schema.model_json_schema(),
        }
        input_attributes = {
            SpanAttributes.INPUT_VALUE: _json(input_payload),
            SpanAttributes.INPUT_MIME_TYPE: "application/json",
            SpanAttributes.LLM_MODEL_NAME: config.model_id,
            "llm.provider": "aws",
            "llm.system": "bedrock",
            "llm.invocation_parameters": _json(
                {
                    "model": config.model_id,
                    "region": config.region,
                    "temperature": config.temperature,
                    "route": config.route.value,
                    "prompt_version": config.prompt_version,
                    "schema_version": config.schema_version,
                    "structured_output_method": config.structured_output_method,
                }
            ),
        }
        for index, (role, content) in enumerate(messages):
            input_attributes[f"llm.input_messages.{index}.message.role"] = role
            input_attributes[f"llm.input_messages.{index}.message.content"] = content
        with self._observability.span(
            "bedrock.converse",
            component="bedrock",
            span_kind=OpenInferenceSpanKindValues.LLM.value,
            attributes={
                "provider.name": "AWS_BEDROCK",
                "model.route": config.route.value,
                "model.id": config.model_id,
                "model.prompt_version": config.prompt_version,
                "model.schema_version": config.schema_version,
                "model.structured_output_method": config.structured_output_method,
                **input_attributes,
            },
        ) as span:
            try:
                invocation = self._invoke(config, schema, messages)
            except Exception as error:
                self._observability.log(
                    EngineeringLogEvent(
                        event_name="bedrock_request_failed",
                        component="bedrock",
                        outcome="ERROR",
                        duration_ms=0,
                        provider_name="AWS_BEDROCK",
                        error_type=type(error).__name__,
                    )
                )
                raise
            self._observability.set_attributes(
                span,
                {
                    "provider.request_id": invocation.provider_request_id,
                    "llm.token_count.prompt": invocation.input_tokens,
                    "llm.token_count.completion": invocation.output_tokens,
                    "llm.token_count.total": (
                        invocation.total_tokens
                        if invocation.total_tokens is not None
                        else invocation.input_tokens + invocation.output_tokens
                    ),
                    SpanAttributes.OUTPUT_VALUE: _json(
                        invocation.provider_output or {"normalized_output": invocation.raw_output}
                    ),
                    SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
                    "llm.output_messages.0.message.role": "assistant",
                    "llm.output_messages.0.message.content": _json(
                        invocation.provider_output or {"normalized_output": invocation.raw_output}
                    ),
                    "model.latency_ms": invocation.latency_ms,
                    "model.stop_reason": invocation.stop_reason,
                },
            )
            self._observability.log(
                EngineeringLogEvent(
                    event_name="bedrock_request_finished",
                    component="bedrock",
                    outcome="OK",
                    duration_ms=invocation.latency_ms,
                    provider_name="AWS_BEDROCK",
                    provider_request_id=invocation.provider_request_id,
                )
            )
            return invocation

    def _invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        model = ChatBedrockConverse(
            model=config.model_id,
            region_name=config.region,
            temperature=config.temperature,
            config=BotoConfig(
                connect_timeout=self._connect_timeout_seconds,
                read_timeout=self._read_timeout_seconds,
                retries={
                    # Workflow retries are durable and auditable; do not hide attempts here.
                    "total_max_attempts": 1,
                    "mode": "standard",
                },
            ),
        )
        structured = model.with_structured_output(
            schema,
            method=config.structured_output_method,
            include_raw=True,
        )
        started = monotonic()
        try:
            with self._permit:
                raw_result = structured.invoke(messages)
        except (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError) as error:
            raise ModelProviderError(
                "Bedrock request timed out.",
                code="BEDROCK_TIMEOUT",
                retryable=True,
            ) from error
        except ClientError as error:
            provider_code = str(error.response.get("Error", {}).get("Code", "UNKNOWN"))
            metadata = _optional_mapping(error.response.get("ResponseMetadata"))
            request_id = metadata.get("RequestId")
            status = metadata.get("HTTPStatusCode")
            throttled = provider_code in {
                "ThrottlingException",
                "TooManyRequestsException",
                "ServiceQuotaExceededException",
            }
            raise ModelProviderError(
                "Bedrock request failed.",
                code=("BEDROCK_THROTTLED" if throttled else "BEDROCK_PROVIDER_ERROR"),
                retryable=throttled or (isinstance(status, int) and status >= 500),
                provider_code=provider_code,
                provider_request_id=(request_id if isinstance(request_id, str) else None),
            ) from error
        except BotoCoreError as error:
            raise ModelProviderError(
                "Bedrock client failed.",
                code="BEDROCK_PROVIDER_ERROR",
                retryable=True,
                provider_code=type(error).__name__,
            ) from error
        latency_ms = max(0, round((monotonic() - started) * 1000))
        result = _mapping(raw_result)
        raw_message = result.get("raw")
        response_metadata = _optional_mapping(getattr(raw_message, "response_metadata", {}))
        usage_metadata = _optional_mapping(getattr(raw_message, "usage_metadata", {}))
        parsed = result.get("parsed")
        parsing_error = result.get("parsing_error")
        wire_normalization: dict[str, object] | None = None
        wire_recovery: dict[str, object] | None = None
        if parsing_error is not None:
            recovered, wire_recovery = _recover_provider_wire_output(schema, raw_message)
            if recovered is not None:
                parsed = recovered
                parsing_error = None
                wire_normalization = {
                    "code": "TOOL_ARGUMENT_JSON_STRING_DECODED",
                    "fields": ["documents"],
                }
        provider_output = {
            "normalized_output": _jsonable(parsed),
            "raw_provider_message": _provider_message(raw_message),
            "parsing_error": _jsonable(parsing_error),
        }
        if wire_normalization is not None:
            provider_output["wire_normalization"] = wire_normalization
        if wire_recovery is not None:
            provider_output["wire_recovery"] = wire_recovery
        if self._observability is not None:
            trace_attributes: dict[str, object] = {
                SpanAttributes.OUTPUT_VALUE: _json(provider_output),
                SpanAttributes.OUTPUT_MIME_TYPE: "application/json",
                "llm.output_messages.0.message.role": "assistant",
                "llm.output_messages.0.message.content": _json(provider_output),
            }
            for source, target in (
                ("input_tokens", SpanAttributes.LLM_TOKEN_COUNT_PROMPT),
                ("output_tokens", SpanAttributes.LLM_TOKEN_COUNT_COMPLETION),
                ("total_tokens", SpanAttributes.LLM_TOKEN_COUNT_TOTAL),
            ):
                value = usage_metadata.get(source)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    trace_attributes[target] = value
            self._observability.set_attributes(
                trace.get_current_span(),
                cast(Mapping[str, AttributeValue], trace_attributes),
            )
        if parsing_error is not None:
            raise ModelSchemaValidationError("Bedrock structured output failed schema parsing.")
        if not isinstance(parsed, BaseModel):
            raise ModelSchemaValidationError(
                "Bedrock structured output did not contain a parsed model."
            )
        aws_metadata = response_metadata.get("ResponseMetadata", {})
        request_metadata = _mapping(aws_metadata)
        request_id = request_metadata.get("RequestId") or response_metadata.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ModelSchemaValidationError(
                "Bedrock response did not include a provider request ID."
            )
        stop_reason = response_metadata.get("stopReason") or response_metadata.get("stop_reason")
        return ModelInvocation(
            raw_output=cast(dict[str, object], parsed.model_dump(mode="json")),
            provider_request_id=request_id,
            input_tokens=_nonnegative_integer(usage_metadata.get("input_tokens", 0)),
            output_tokens=_nonnegative_integer(usage_metadata.get("output_tokens", 0)),
            latency_ms=latency_ms,
            stop_reason=(stop_reason if isinstance(stop_reason, str) else "UNKNOWN"),
            provider_output=provider_output,
            total_tokens=_nonnegative_integer(
                usage_metadata.get(
                    "total_tokens",
                    _nonnegative_integer(usage_metadata.get("input_tokens", 0))
                    + _nonnegative_integer(usage_metadata.get("output_tokens", 0)),
                )
            ),
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ModelSchemaValidationError("Bedrock response metadata has an invalid shape.")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelSchemaValidationError("Bedrock token metadata has an invalid shape.")
    return value


def _recover_provider_wire_output(
    schema: type[BaseModel],
    raw_message: object,
) -> tuple[BaseModel | None, dict[str, object] | None]:
    """Recover tolerated provider-wire quirks before strict backend validation.

    Some Bedrock function-calling models return the v4 `documents` array as a
    JSON-encoded string inside the tool arguments. That is a provider transport
    shape error, not a semantic triage error, so normalize it for the tolerant v4
    wire contract only and then let Pydantic validate the full object normally.
    """

    if schema.__name__ != "TriageProviderOutputV4":
        return None, None
    for tool_call in _tool_calls(raw_message):
        if tool_call.get("name") != schema.__name__:
            continue
        args = tool_call.get("args")
        if not isinstance(args, Mapping):
            return None, {
                "attempted": True,
                "field": "documents",
                "outcome": "REJECTED",
                "reason": "TOOL_ARGUMENTS_NOT_OBJECT",
            }
        documents = args.get("documents")
        if not isinstance(documents, str):
            return None, {
                "attempted": True,
                "field": "documents",
                "outcome": "SKIPPED",
                "reason": "DOCUMENTS_NOT_JSON_STRING",
            }
        try:
            decoded_documents, syntax_repair = _decode_v4_documents(documents)
        except json.JSONDecodeError as error:
            return None, {
                "attempted": True,
                "field": "documents",
                "outcome": "REJECTED",
                "reason": "DOCUMENTS_INVALID_JSON",
                "validation_error": error.msg,
                "position": error.pos,
                "line": error.lineno,
                "column": error.colno,
            }
        normalized_args = dict(args)
        normalized_args["documents"] = decoded_documents
        try:
            diagnostic: dict[str, object] = {
                "attempted": True,
                "field": "documents",
                "outcome": "RECOVERED",
            }
            if syntax_repair is not None:
                diagnostic["repair"] = syntax_repair
            return schema.model_validate(normalized_args), diagnostic
        except ValidationError as error:
            return None, {
                "attempted": True,
                "field": "documents",
                "outcome": "REJECTED",
                "reason": "DECODED_ARGUMENTS_SCHEMA_INVALID",
                "validation_error": str(error),
            }
    return None, None


def _decode_v4_documents(documents: str) -> tuple[object, str | None]:
    """Decode a v4 documents argument with one bounded DeepSeek wire repair.

    Some DeepSeek tool calls append exactly one closing brace after an otherwise
    complete JSON array. Accept only that isolated suffix; malformed JSON and
    all other trailing data remain schema failures.
    """

    try:
        return json.loads(documents), None
    except json.JSONDecodeError as error:
        if error.msg != "Extra data":
            raise
        decoded, end = json.JSONDecoder().raw_decode(documents)
        if documents[end:].strip() != "}":
            raise
        return decoded, "SINGLE_TRAILING_CLOSE_BRACE_DROPPED"


def _tool_calls(raw_message: object) -> tuple[Mapping[str, object], ...]:
    tool_calls = getattr(raw_message, "tool_calls", ())
    if not isinstance(tool_calls, list | tuple):
        return ()
    return tuple(tool_call for tool_call in tool_calls if isinstance(tool_call, Mapping))


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _provider_message(message: object) -> dict[str, object]:
    if isinstance(message, BaseModel):
        dumped = message.model_dump(mode="json")
        return cast(dict[str, object], dumped)
    return {
        "id": _jsonable(getattr(message, "id", None)),
        "type": _jsonable(getattr(message, "type", None)),
        "content": _jsonable(getattr(message, "content", None)),
        "additional_kwargs": _jsonable(getattr(message, "additional_kwargs", {})),
        "response_metadata": _jsonable(getattr(message, "response_metadata", {})),
        "usage_metadata": _jsonable(getattr(message, "usage_metadata", {})),
        "tool_calls": _jsonable(getattr(message, "tool_calls", [])),
        "invalid_tool_calls": _jsonable(getattr(message, "invalid_tool_calls", [])),
    }


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(child) for child in value]
    if isinstance(value, Exception):
        return {"type": type(value).__name__, "message": str(value)}
    return repr(value)
