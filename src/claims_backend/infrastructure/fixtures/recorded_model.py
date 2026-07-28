from copy import deepcopy
from hashlib import sha256

from pydantic import BaseModel

from claims_backend.domain.extraction import ModelRoute
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation


class RecordedStructuredModelTransport:
    def __init__(
        self,
        responses: dict[ModelRoute, dict[str, object]],
    ) -> None:
        self._responses = deepcopy(responses)
        self.calls: list[ModelRoute] = []

    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        del schema, messages
        self.calls.append(config.route)
        raw_output = deepcopy(self._responses[config.route])
        request_key = (f"{config.route.value}:{config.model_id}:{config.prompt_version}").encode()
        return ModelInvocation(
            raw_output=raw_output,
            provider_request_id=f"recorded-{sha256(request_key).hexdigest()[:24]}",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            stop_reason="RECORDED",
        )
