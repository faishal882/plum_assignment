from dataclasses import dataclass
from typing import Literal

from claims_backend.domain.extraction import ModelRoute
from claims_backend.domain.workflow import ExecutionContract


@dataclass(frozen=True, slots=True)
class ModelRouteConfig:
    route: ModelRoute
    model_id: str
    region: str
    prompt_version: str
    schema_version: str
    enabled: bool
    evaluation_approved: bool
    temperature: int = 0
    structured_output_method: Literal["function_calling", "json_schema"] = "function_calling"

    def __post_init__(self) -> None:
        for name, value in (
            ("model_id", self.model_id),
            ("region", self.region),
            ("prompt_version", self.prompt_version),
            ("schema_version", self.schema_version),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty.")
        if self.temperature != 0:
            raise ValueError("Evidence extraction routes must use temperature zero.")


class ModelRouteUnavailableError(RuntimeError):
    pass


class ModelRouter:
    def __init__(self, routes: tuple[ModelRouteConfig, ...]) -> None:
        self._routes = {route.route: route for route in routes}
        if len(self._routes) != len(routes):
            raise ValueError("Model routes must be unique.")

    @classmethod
    def default(cls, *, region: str, model_id: str) -> "ModelRouter":
        return cls(
            (
                ModelRouteConfig(
                    route=ModelRoute.FAST_TRIAGE,
                    model_id=model_id,
                    region=region,
                    prompt_version="fast-triage-prompt-v1",
                    schema_version="triage-output-v2",
                    enabled=True,
                    evaluation_approved=True,
                ),
                ModelRouteConfig(
                    route=ModelRoute.COMPLEX_EXTRACTION,
                    model_id=model_id,
                    region=region,
                    prompt_version="complex-extraction-prompt-v4",
                    schema_version="complex-extraction-v1",
                    enabled=True,
                    evaluation_approved=True,
                ),
            )
        )

    @classmethod
    def from_execution_contract(cls, contract: ExecutionContract) -> "ModelRouter":
        """Rebuild only a known, pinned route set from durable workflow metadata."""
        routes: list[ModelRouteConfig] = []
        for route, model_id, region, prompt_version, schema_version in contract.model_routes:
            try:
                model_route = ModelRoute(route)
            except ValueError as error:
                raise ModelRouteUnavailableError(
                    f"Persisted model route {route!r} is unsupported."
                ) from error
            if model_route is ModelRoute.FAST_TRIAGE and (
                prompt_version != "fast-triage-prompt-v1" or schema_version != "triage-output-v2"
            ):
                raise ModelRouteUnavailableError("Persisted fast triage contract is unsupported.")
            if model_route is ModelRoute.COMPLEX_EXTRACTION and (
                prompt_version
                not in {
                    "complex-extraction-prompt-v3",
                    "complex-extraction-prompt-v4",
                }
                or schema_version != "complex-extraction-v1"
            ):
                raise ModelRouteUnavailableError(
                    "Persisted complex extraction contract is unsupported."
                )
            routes.append(
                ModelRouteConfig(
                    route=model_route,
                    model_id=model_id,
                    region=region,
                    prompt_version=prompt_version,
                    schema_version=schema_version,
                    enabled=True,
                    evaluation_approved=True,
                )
            )
        expected = {ModelRoute.FAST_TRIAGE, ModelRoute.COMPLEX_EXTRACTION}
        if {route.route for route in routes} != expected:
            raise ModelRouteUnavailableError(
                "Persisted execution contract has an incomplete route set."
            )
        return cls(tuple(routes))

    def resolve(self, route: ModelRoute) -> ModelRouteConfig:
        config = self._routes.get(route)
        if config is None or not config.enabled or not config.evaluation_approved:
            raise ModelRouteUnavailableError(
                f"Model route {route.value} is not enabled and evaluation-approved."
            )
        return config

    def enabled_routes(self) -> tuple[ModelRouteConfig, ...]:
        """Return approved route definitions in stable order for workflow pinning."""
        return tuple(
            self.resolve(route) for route in sorted(self._routes, key=lambda item: item.value)
        )
