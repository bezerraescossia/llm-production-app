"""Every route and documented status code is exercised and validated against the contract."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from openapi_spec_validator import validate

from ai_services.config import Settings
from ai_services.errors import ErrorCode, ServiceError
from ai_services.gateway.config import GatewayConfig, ModelCandidate, RetryPolicy
from ai_services.main import create_app
from tests.conftest import TENANT_HEADERS, TOKEN_A, VALID_BODY, auth
from tests.contract.helpers import load_openapi, response_schema, schema_validator

OPENAPI = load_openapi()
CHAT = "/v1/chat/stream"
# Documented statuses that are covered by dedicated tests below instead of the case table.
COVERED_ELSEWHERE = {(CHAT, "post", 429), (CHAT, "post", 500)}


@asynccontextmanager
async def running(
    gateway_config: GatewayConfig | None = None, **overrides: Any
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        **overrides,
    )
    app = create_app(settings, gateway_config)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield app, client


def failing_gateway(models: list[str], max_input_tokens: int | None = None) -> GatewayConfig:
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": models, "large": ["stub/default"]}
    )
    cfg.retry = RetryPolicy(
        max_attempts_per_model=2, backoff_base_seconds=0.001, backoff_max_seconds=0.002
    )
    if max_input_tokens is not None:
        cfg.tiers["medium"].models = [
            ModelCandidate(provider="stub", model_id="default", max_input_tokens=max_input_tokens)
        ]
    return cfg


def test_contract_is_a_valid_openapi_document() -> None:
    validate(OPENAPI)


def test_contract_version_is_1_1_0() -> None:
    assert OPENAPI["info"]["version"] == "1.1.0"


async def call(case: str) -> httpx.Response:
    big = {"messages": [{"role": "user", "content": "x" * 30000}] * 12}  # about 360 KB
    async with running(readiness_dependencies="down=127.0.0.1:1") as (app, c):
        match case:
            case "chat_200":
                return await c.post(CHAT, json=VALID_BODY, headers=auth())
            case "chat_400":
                return await c.post(
                    CHAT, json=VALID_BODY, headers={"Authorization": f"Bearer {TOKEN_A}"}
                )
            case "chat_401":
                return await c.post(CHAT, json=VALID_BODY, headers=TENANT_HEADERS)
            case "chat_413":
                return await c.post(CHAT, json=big, headers=auth())
            case "chat_422_validation":
                return await c.post(CHAT, json={"messages": []}, headers=auth())
            case "chat_422_history":
                return await c.post(
                    CHAT, json={"messages": [VALID_BODY["messages"][0]] * 101}, headers=auth()
                )
            case "chat_503":
                app.state.begin_shutdown()
                return await c.post(CHAT, json=VALID_BODY, headers=auth())
            case "chat_502":
                return await post_with(failing_gateway(["stub/fail-auth"]))
            case "chat_504":
                return await post_with(failing_gateway(["stub/fail-timeout"]))
            case "chat_503_upstream":
                return await post_with(failing_gateway(["stub/fail-temporary"]))
            case "chat_422_input_too_large":
                return await post_with(
                    failing_gateway(["stub/default"], max_input_tokens=5), long=True
                )
            case "live_200":
                return await c.get("/v1/health/live")
            case "ready_503":
                return await c.get("/v1/health/ready")
            case "contract_200":
                return await c.get("/v1/contract")
    raise AssertionError(case)


async def post_with(cfg: GatewayConfig, long: bool = False) -> httpx.Response:
    body = {"messages": [{"role": "user", "content": "x" * (300 if long else 5)}]}
    async with running(cfg) as (_app, c):
        return await c.post(CHAT, json=body, headers=auth())


async def call_ready_200() -> httpx.Response:
    async with running() as (_app, c):
        return await c.get("/v1/health/ready")


CASES = {
    "chat_200": (CHAT, "post", 200),
    "chat_400": (CHAT, "post", 400),
    "chat_401": (CHAT, "post", 401),
    "chat_413": (CHAT, "post", 413),
    "chat_422_validation": (CHAT, "post", 422),
    "chat_422_history": (CHAT, "post", 422),
    "chat_503": (CHAT, "post", 503),
    "chat_503_upstream": (CHAT, "post", 503),
    "chat_502": (CHAT, "post", 502),
    "chat_504": (CHAT, "post", 504),
    "chat_422_input_too_large": (CHAT, "post", 422),
    "live_200": ("/v1/health/live", "get", 200),
    "ready_503": ("/v1/health/ready", "get", 503),
    "contract_200": ("/v1/contract", "get", 200),
}


@pytest.mark.parametrize("case", CASES)
async def test_response_conforms_to_contract(case: str) -> None:
    path, method, status = CASES[case]
    r = await call(case)
    assert r.status_code == status, r.text
    assert r.headers["x-request-id"] and r.headers["x-contract-version"]
    if "text/event-stream" in r.headers["content-type"]:
        return  # events are validated in test_event_schema.py
    schema_validator(OPENAPI, response_schema(OPENAPI, path, method, status)).validate(r.json())


async def test_ready_200_conforms() -> None:
    r = await call_ready_200()
    assert r.status_code == 200
    schema_validator(OPENAPI, response_schema(OPENAPI, "/v1/health/ready", "get", 200)).validate(
        r.json()
    )


async def test_ready_with_credential_includes_dependencies_per_contract() -> None:
    async with running(readiness_dependencies="down=127.0.0.1:1") as (_app, c):
        r = await c.get("/v1/health/ready", headers={"Authorization": f"Bearer {TOKEN_A}"})
    assert r.status_code == 503
    schema_validator(OPENAPI, response_schema(OPENAPI, "/v1/health/ready", "get", 503)).validate(
        r.json()
    )
    assert r.json()["dependencies"] == [{"name": "down", "status": "down"}]


async def test_reserved_and_internal_errors_conform() -> None:
    async with running() as (app, c):

        async def limited() -> None:
            raise ServiceError(ErrorCode.RATE_LIMITED, "slow", retry_after_seconds=2)

        async def boom() -> None:
            raise RuntimeError("secret detail")

        app.add_api_route("/v1/_limited", limited)
        app.add_api_route("/v1/_boom", boom)
        limited_r = await c.get("/v1/_limited")
        boom_r = await c.get("/v1/_boom")
    assert limited_r.status_code == 429 and limited_r.headers["retry-after"] == "2"
    assert boom_r.status_code == 500
    for status, r in ((429, limited_r), (500, boom_r)):
        schema_validator(OPENAPI, response_schema(OPENAPI, CHAT, "post", status)).validate(r.json())


def test_every_documented_status_is_covered() -> None:
    documented = {
        (path, method, int(status))
        for path, ops in OPENAPI["paths"].items()
        for method, op in ops.items()
        for status in op["responses"]
    }
    covered = set(CASES.values()) | COVERED_ELSEWHERE | {("/v1/health/ready", "get", 200)}
    assert documented == covered
