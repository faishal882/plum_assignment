from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.review_routes import router as review_router
from claims_backend.api.routes import router
from claims_backend.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    engine = create_async_engine(resolved_settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(
        title="Plum Claims Backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.include_router(router)
    app.include_router(review_router)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    return app


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
