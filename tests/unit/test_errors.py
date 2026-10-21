import httpx
import pytest
from fastapi import FastAPI

from ai_services.context import RequestContext, set_context
from ai_services.errors import (
    STATUS,
    ErrorCode,
    ServiceError,
    error_body,
    install_error_handlers,
)
from ai_services.middleware import RequestContextMiddleware

EXPECTED = {
    "unauthorized": 401,
    "invalid_identity": 400,
    "validation_error": 422,
    "history_too_long": 422,
    "payload_too_large": 413,
    "rate_limited": 429,
    "shutting_down": 503,
    "not_found": 404,
    "method_not_allowed": 405,
    "internal_error": 500,
}


def test_every_code_maps_to_documented_status() -> None:
    assert {c.value: STATUS[c] for c in ErrorCode} == EXPECTED


def test_body_shape_minimal_and_full() -> None:
    assert error_body(ErrorCode.UNAUTHORIZED, "no", "req-12345678") == {
        "error": {"code": "unauthorized", "message": "no", "request_id": "req-12345678"}
    }
    full = error_body(
        ErrorCode.RATE_LIMITED, "slow down", "req-12345678", details={"a": 1}, retry_after_seconds=7
    )
    assert full["error"]["details"] == {"a": 1}
    assert full["error"]["retry_after_seconds"] == 7


def build_app() -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware, contract_version="1.0.0")

    @app.get("/limited")
    async def limited() -> None:
        raise ServiceError(ErrorCode.RATE_LIMITED, "slow", retry_after_seconds=7)

    @app.get("/draining")
    async def draining() -> None:
        raise ServiceError(ErrorCode.SHUTTING_DOWN, "bye", retry_after_seconds=3)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret database password hunter2")

    return app


@pytest.fixture
async def c() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app()), base_url="http://t")


async def test_retry_after_header_for_429_and_503(c: httpx.AsyncClient) -> None:
    r = await c.get("/limited")
    assert r.status_code == 429 and r.headers["retry-after"] == "7"
    assert r.json()["error"]["retry_after_seconds"] == 7
    r = await c.get("/draining")
    assert r.status_code == 503 and r.headers["retry-after"] == "3"


async def test_internal_error_is_generic_and_carries_request_id(c: httpx.AsyncClient) -> None:
    r = await c.get("/boom", headers={"X-Request-Id": "client-req-0001"})
    assert r.status_code == 500
    body = r.json()["error"]
    assert body["code"] == "internal_error"
    assert "hunter2" not in r.text and "RuntimeError" not in r.text
    assert body["request_id"] == "client-req-0001"
    assert r.headers["x-request-id"] == "client-req-0001"


def test_set_context_helper_available() -> None:
    token = set_context(RequestContext(request_id="abc12345", contract_version="1.0.0"))
    assert token is not None
