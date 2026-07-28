from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from claims_backend.model.routing import ModelRouteConfig


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    raw_output: dict[str, object]
    provider_request_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str


class StructuredModelTransport(Protocol):
    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation: ...
