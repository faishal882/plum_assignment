from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from claims_backend.api.health import router as health_router
from claims_backend.api.review_routes import router as review_router
from claims_backend.api.routes import router
from claims_backend.config import Settings
from claims_backend.observability import (
    EngineeringLogEvent,
    Observability,
)
from claims_backend.runtime.composition import create_process_runtime


def create_app(
    settings: Settings | None = None,
    *,
    observability: Observability | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    runtime = create_process_runtime(
        resolved_settings,
        process_name="api",
        observability=observability,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await runtime.close()

    app = FastAPI(
        title="Plum Claims Backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.runtime = runtime
    app.state.engine = runtime.engine
    app.state.session_factory = runtime.session_factory
    app.state.observability = runtime.observability
    if runtime.observability is not None:
        _install_observability_middleware(app, runtime.observability)
    app.include_router(router)
    app.include_router(review_router)
    app.include_router(health_router)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    return app


def _install_observability_middleware(
    app: FastAPI,
    observability: Observability,
) -> None:
    @app.middleware("http")
    async def observe_request(request: Request, call_next: Any) -> Any:
        started = monotonic()
        with observability.span(
            "api.request",
            component="api",
            attributes={"http.request.method": request.method},
        ) as span:
            try:
                response = await call_next(request)
            except Exception as error:
                duration_ms = max(0, round((monotonic() - started) * 1000))
                observability.log(
                    EngineeringLogEvent(
                        event_name="api_request_failed",
                        component="api",
                        outcome="ERROR",
                        duration_ms=duration_ms,
                        error_type=type(error).__name__,
                    )
                )
                raise
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            duration_ms = max(0, round((monotonic() - started) * 1000))
            observability.set_attributes(
                span,
                {
                    "http.route": str(route_path),
                    "http.response.status_code": response.status_code,
                },
            )
            observability.log(
                EngineeringLogEvent(
                    event_name="api_request_finished",
                    component="api",
                    outcome=("OK" if response.status_code < 500 else "ERROR"),
                    duration_ms=duration_ms,
                )
            )
            return response


async def _request_validation_error(
    _: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    details = [
        {
            "location": list(issue["loc"]),
            "message": issue["msg"],
            "type": issue["type"],
        }
        for issue in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "Request validation failed.",
                "details": details,
            }
        },
    )


async def _http_error(_: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, HTTPException):
        raise error
    detail: Any = error.detail
    if isinstance(detail, dict) and {"code", "message"} <= detail.keys():
        body = {"error": detail}
    else:
        body = {
            "error": {
                "code": "HTTP_ERROR",
                "message": str(detail),
                "details": [],
            }
        }
    return JSONResponse(status_code=error.status_code, content=body, headers=error.headers)


app = create_app()
