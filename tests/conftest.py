"""Shared fixtures: settings, app, in-process client and a live Uvicorn server."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from ai_services.config import Settings
from ai_services.main import create_app

TOKEN_A = "token-a-" + "a" * 32
TOKEN_B = "token-b-" + "b" * 32
TENANT_HEADERS = {"X-Tenant-Id": "acme", "X-User-Id": "u-1"}
VALID_BODY = {"messages": [{"role": "user", "content": "hello"}]}


def auth(token: str = TOKEN_A, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **TENANT_HEADERS, **extra}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A, TOKEN_B],
        readiness_dependencies="",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@contextlib.asynccontextmanager
async def run_server(app: FastAPI) -> AsyncIterator[tuple[str, uvicorn.Server]]:
    """Run the app under a real Uvicorn server on a free port (true streaming, real shutdown)."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.should_exit = True
        await task


@pytest_asyncio.fixture
async def live(app: FastAPI) -> AsyncIterator[tuple[str, uvicorn.Server]]:
    async with run_server(app) as pair:
        yield pair


def parse_sse(text: str) -> list[dict[str, str]]:
    """Parse a full SSE body into a list of {id, event, data} dicts."""
    frames: list[dict[str, str]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        frame: dict[str, str] = {}
        for line in block.split("\n"):
            if ":" in line and not line.startswith(":"):
                key, _, value = line.partition(":")
                frame[key] = value.lstrip()
        if frame:
            frames.append(frame)
    return frames
