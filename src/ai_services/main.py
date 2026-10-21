"""Application factory."""

import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from ai_services.api.v1 import chat, contract, health
from ai_services.auth import ServiceAuthMiddleware
from ai_services.config import Settings, load_settings
from ai_services.contract_version import load_contract_version
from ai_services.errors import install_error_handlers
from ai_services.logging import configure_logging, get_logger
from ai_services.middleware import (
    BodyLimitMiddleware,
    RequestContextMiddleware,
    ShutdownGateMiddleware,
)

log = get_logger(__name__)


def _install_sigterm_hook(app: FastAPI) -> Any:
    """Mark the app as shutting down when SIGTERM arrives, then defer to the previous handler."""
    try:
        previous = signal.getsignal(signal.SIGTERM)

        def handler(signum: int, frame: Any) -> None:
            app.state.begin_shutdown()
            if callable(previous):
                previous(signum, frame)

        signal.signal(signal.SIGTERM, handler)
    except ValueError:  # not in the main thread (for example under some test runners)
        return None
    return previous


def _install_openapi(app: FastAPI) -> None:
    """Document the bearer scheme so Swagger UI's Authorize button works.

    Authentication runs in middleware, so FastAPI does not know about it. Routes that are open
    override the global requirement with their own `security` (see health.py and contract.py).
    """

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schema.setdefault("components", {}).setdefault("securitySchemes", {})[
                "serviceToken"
            ] = {"type": "http", "scheme": "bearer"}
            schema["security"] = [{"serviceToken": []}]
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]  # pyright: ignore[reportAttributeAccessIssue]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    contract_version = load_contract_version()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        previous = _install_sigterm_hook(app)
        log.info("startup", contract_version=contract_version)
        yield
        log.info("shutdown")
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)

    app = FastAPI(
        title="AI-Services API",
        version=contract_version,
        openapi_url="/v1/openapi.json" if settings.enable_docs else None,
        docs_url="/v1/docs" if settings.enable_docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    _install_openapi(app)
    app.state.settings = settings
    app.state.shutting_down = False
    app.state.active_streams = 0
    app.state.contract_version = contract_version

    def begin_shutdown() -> None:
        app.state.shutting_down = True

    app.state.begin_shutdown = begin_shutdown

    install_error_handlers(app)
    app.include_router(chat.router)
    app.include_router(health.router)
    app.include_router(contract.router)

    # Added innermost first. Request flow: context, shutdown gate, auth, body limit, routes.
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(ServiceAuthMiddleware, tokens=settings.service_tokens)
    app.add_middleware(ShutdownGateMiddleware)
    app.add_middleware(RequestContextMiddleware, contract_version=contract_version)
    return app


def get_app() -> FastAPI:
    """Uvicorn factory entry point: `uvicorn ai_services.main:get_app --factory`."""
    return create_app()
