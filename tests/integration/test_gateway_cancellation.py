"""Abandoning a request stops the provider work (FR-015, SC-005)."""

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from ai_services.config import Settings
from ai_services.gateway.config import GatewayConfig
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, run_server


def make_app(medium: list[str], delay_ms: int = 0) -> FastAPI:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        placeholder_token_delay_ms=delay_ms,
    )
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": medium, "large": ["stub/default"]}
    )
    return create_app(settings, gateway_config=cfg)


async def wait_until(predicate, seconds: float) -> float:  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        if predicate():
            return time.perf_counter() - start
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


async def test_a_disconnect_mid_stream_stops_the_provider_within_a_second() -> None:
    app = make_app(["stub/default"], delay_ms=200)
    async with run_server(app) as (base, _server):
        async with httpx.AsyncClient(base_url=base, timeout=5) as c:
            async with c.stream("POST", "/v1/chat/stream", json=VALID_BODY, headers=auth()) as r:
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        break
                assert app.state.stub.active == 1
        gone = time.perf_counter()
        elapsed = await wait_until(lambda: app.state.stub.active == 0, 1.0)
        assert elapsed < 1.0 and time.perf_counter() - gone < 1.0
        await wait_until(lambda: app.state.active_streams == 0, 1.0)


async def test_a_disconnect_while_waiting_for_the_first_output_stops_the_provider() -> None:
    app = make_app(["stub/stall"])  # never answers; the default first-output limit is 15 s
    async with run_server(app) as (base, _server):
        client = httpx.AsyncClient(base_url=base, timeout=5)
        task = asyncio.create_task(client.post("/v1/chat/stream", json=VALID_BODY, headers=auth()))
        await wait_until(lambda: app.state.stub.active == 1, 2.0)  # the call is in flight
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()  # the connection is gone
        elapsed = await wait_until(lambda: app.state.stub.active == 0, 1.5)
        assert elapsed < 1.5
        await wait_until(lambda: app.state.active_streams == 0, 1.0)
