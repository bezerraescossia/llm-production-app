"""Error codes, the single error shape, and exception handlers."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_services.context import current_request_id


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    INVALID_IDENTITY = "invalid_identity"
    VALIDATION_ERROR = "validation_error"
    HISTORY_TOO_LONG = "history_too_long"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    RATE_LIMITED = "rate_limited"
    SHUTTING_DOWN = "shutting_down"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INTERNAL_ERROR = "internal_error"


STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_IDENTITY: 400,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.HISTORY_TOO_LONG: 422,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SHUTTING_DOWN: 503,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ServiceError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.retry_after_seconds = retry_after_seconds

    @property
    def status_code(self) -> int:
        return STATUS[self.code]


def error_body(
    code: ErrorCode,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
    retry_after_seconds: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code.value, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    if retry_after_seconds is not None:
        body["retry_after_seconds"] = retry_after_seconds
    return {"error": body}


def error_response(err: ServiceError) -> JSONResponse:
    headers = {}
    if err.retry_after_seconds is not None:
        headers["Retry-After"] = str(err.retry_after_seconds)
    return JSONResponse(
        error_body(
            err.code, err.message, current_request_id(), err.details, err.retry_after_seconds
        ),
        status_code=err.status_code,
        headers=headers,
    )


def internal_error_response() -> JSONResponse:
    return error_response(ServiceError(ErrorCode.INTERNAL_ERROR, "An internal error occurred."))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        # Never echo input values: they may carry user content.
        details = {
            "errors": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in errors]
        }
        too_long = any(e["type"] == "too_long" and e["loc"][-1] == "messages" for e in errors)
        if too_long:
            return error_response(
                ServiceError(
                    ErrorCode.HISTORY_TOO_LONG, "The message history is too long.", details=details
                )
            )
        return error_response(
            ServiceError(ErrorCode.VALIDATION_ERROR, "The request is invalid.", details=details)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            return error_response(ServiceError(ErrorCode.METHOD_NOT_ALLOWED, "Method not allowed."))
        if exc.status_code == 404:
            return error_response(ServiceError(ErrorCode.NOT_FOUND, "Not found."))
        if exc.status_code == 413:
            return error_response(
                ServiceError(ErrorCode.PAYLOAD_TOO_LARGE, "The request body is too large.")
            )
        if exc.status_code == 400:
            return error_response(
                ServiceError(ErrorCode.VALIDATION_ERROR, "The request body could not be read.")
            )
        return internal_error_response()
