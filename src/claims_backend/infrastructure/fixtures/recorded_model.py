from copy import deepcopy
from hashlib import sha256

from pydantic import BaseModel

from claims_backend.domain.extraction import ModelRoute
from claims_backend.model.routing import ModelRouteConfig
from claims_backend.model.transport import ModelInvocation


class RecordedStructuredModelTransport:
    def __init__(
        self,
        responses: dict[
            ModelRoute,
            dict[str, object] | tuple[dict[str, object], ...],
        ],
    ) -> None:
        self._repeatable_routes = {
            route
            for route, route_responses in responses.items()
            if isinstance(route_responses, dict)
        }
        self._responses = {
            route: (
                deepcopy(route_responses)
                if isinstance(route_responses, tuple)
                else (deepcopy(route_responses),)
            )
            for route, route_responses in responses.items()
        }
        self._next_response = {route: 0 for route in responses}
        self.calls: list[ModelRoute] = []

    def invoke(
        self,
        config: ModelRouteConfig,
        schema: type[BaseModel],
        messages: list[tuple[str, str]],
    ) -> ModelInvocation:
        del schema, messages
        self.calls.append(config.route)
        ordinal = self._next_response[config.route]
        route_responses = self._responses[config.route]
        if ordinal >= len(route_responses):
            if config.route in self._repeatable_routes:
                ordinal = 0
            else:
                raise RuntimeError(f"No recorded response remains for route {config.route.value}.")
        raw_output = deepcopy(route_responses[ordinal])
        self._next_response[config.route] += 1
        request_key = (
            f"{config.route.value}:{config.model_id}:{config.prompt_version}:"
            f"{config.structured_output_method}:{ordinal}"
        ).encode()
        return ModelInvocation(
            raw_output=raw_output,
            provider_request_id=f"recorded-{sha256(request_key).hexdigest()[:24]}",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            stop_reason="RECORDED",
        )
