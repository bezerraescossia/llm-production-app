"""ASGI middleware: request context and id, response headers, unhandled-error conversion."""

import time
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_services.context import RequestContext, reset_context, set_context
from ai_services.errors import ErrorCode, ServiceError, error_response, internal_error_response
from ai_services.logging import get_logger
from ai_services.schemas import REQUEST_ID_PATTERN

log = get_logger(__name__)


class RequestContextMiddleware:
    """Binds a RequestContext, echoes X-Request-Id and X-Contract-Version, and turns an
    unhandled exception into the documented internal_error response (detail only in logs)."""

    def __init__(self, app: ASGIApp, contract_version: str) -> None:
        self.app = app
        self.contract_version = contract_version

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get("x-request-id")
        request_id = (
            supplied
            if supplied is not None and REQUEST_ID_PATTERN.fullmatch(supplied)
            else str(uuid.uuid4())
        )
        token = set_context(RequestContext(request_id, self.contract_version))
        started = False
        status = 500
        began = time.perf_counter()

        async def send_with_headers(message: Message) -> None:
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
                headers["X-Contract-Version"] = self.contract_version
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            log.error("unhandled_exception", error_type=type(exc).__name__, exc_info=True)
            if started:
                raise
            await internal_error_response()(scope, receive, send_with_headers)
        finally:
            # Method, path (no query string), status and timing only: never headers or bodies.
            log.info(
                "request_finished",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - began) * 1000, 1),
            )
            reset_context(token)


def header_value(scope: Scope, name: str) -> Any:
    return Headers(scope=scope).get(name)


class _BodyTooLargeError(StarletteHTTPException):
    """An HTTPException so FastAPI's body reader re-raises it instead of masking it as a 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413)


class BodyLimitMiddleware:
    """Rejects bodies over the limit with 413, by Content-Length or while streaming."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject()(scope, receive, send)
            return

        total = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodyTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if started:
                raise
            await self._reject()(scope, receive, send)

    def _reject(self) -> Any:
        return error_response(
            ServiceError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"The request body exceeds {self.max_bytes} bytes.",
            )
        )


class ShutdownGateMiddleware:
    """Refuses new chat requests with 503 once shutdown has begun."""

    def __init__(self, app: ASGIApp, retry_after_seconds: int = 5) -> None:
        self.app = app
        self.retry_after_seconds = retry_after_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/v1/chat/")
            and scope["app"].state.shutting_down
        ):
            err = ServiceError(
                ErrorCode.SHUTTING_DOWN,
                "The service is shutting down; retry shortly.",
                retry_after_seconds=self.retry_after_seconds,
            )
            await error_response(err)(scope, receive, send)
            return
        await self.app(scope, receive, send)
