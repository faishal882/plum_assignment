from collections.abc import Mapping
from threading import BoundedSemaphore
from time import monotonic
from typing import cast

from botocore.config import Config as BotoConfig  # type: ignore[import-untyped]
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel

from claims_backend.domain.extraction import ModelSchemaValidationError
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation


class ChatBedrockConverseTransport:
    def __init__(
        self,
        *,
        connect_timeout_seconds: int = 30,
        read_timeout_seconds: int = 90,
        max_attempts: int = 3,
        concurrency_limit: int = 2,
    ) -> None:
        for name, value in (
            ("connect_timeout_seconds", connect_timeout_seconds),
            ("read_timeout_seconds", read_timeout_seconds),
            ("max_attempts", max_attempts),
            ("concurrency_limit", concurrency_limit),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if max_attempts > 3:
            raise ValueError("max_attempts cannot exceed three")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._max_attempts = max_attempts
        self._permit = BoundedSemaphore(concurrency_limit)

    def invoke(
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
                    "total_max_attempts": self._max_attempts,
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
        with self._permit:
            raw_result = structured.invoke(messages)
        latency_ms = max(0, round((monotonic() - started) * 1000))
        result = _mapping(raw_result)
        if result.get("parsing_error") is not None:
            raise ModelSchemaValidationError("Bedrock structured output failed schema parsing.")
        parsed = result.get("parsed")
        if not isinstance(parsed, BaseModel):
            raise ModelSchemaValidationError(
                "Bedrock structured output did not contain a parsed model."
            )
        raw_message = result.get("raw")
        response_metadata = _mapping(getattr(raw_message, "response_metadata", {}))
        usage_metadata = _mapping(getattr(raw_message, "usage_metadata", {}))
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
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ModelSchemaValidationError("Bedrock response metadata has an invalid shape.")
    return value


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelSchemaValidationError("Bedrock token metadata has an invalid shape.")
    return value
