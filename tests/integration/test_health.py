import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.main import create_app
from tests.conftest import TOKEN_A

TOKEN = {"Authorization": f"Bearer {TOKEN_A}"}


@asynccontextmanager
async def running(deps: str = "") -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        readiness_dependencies=deps,
    )
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client, app


async def serve(port: int = 0) -> asyncio.Server:
    async def handler(_r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        w.close()

    return await asyncio.start_server(handler, "127.0.0.1", port)


async def test_liveness_is_open_and_does_no_dependency_work() -> None:
    async with running("blackhole=10.255.255.1:9") as (c, _):
        start = time.perf_counter()
        r = await c.get("/v1/health/live")
        assert time.perf_counter() - start < 0.5  # a timed-out probe would take about 1 s
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_readiness_without_token_returns_status_only() -> None:
    server = await serve()
    port = server.sockets[0].getsockname()[1]
    try:
        async with running(f"db=127.0.0.1:{port}") as (c, _):
            anon = await c.get("/v1/health/ready")
            bad = await c.get("/v1/health/ready", headers={"Authorization": "Bearer nope"})
            full = await c.get("/v1/health/ready", headers=TOKEN)
    finally:
        server.close()
    assert anon.status_code == 200 and anon.json() == {"status": "ready"}
    assert bad.json() == {"status": "ready"}
    assert full.json() == {"status": "ready", "dependencies": [{"name": "db", "status": "up"}]}


async def test_dependency_down_is_503_detail_only_with_token() -> None:
    async with running("db=127.0.0.1:1") as (c, _):
        anon = await c.get("/v1/health/ready")
        full = await c.get("/v1/health/ready", headers=TOKEN)
        live = await c.get("/v1/health/live")
    assert anon.status_code == 503 and anon.json() == {"status": "not_ready"}
    assert full.status_code == 503
    assert full.json()["dependencies"] == [{"name": "db", "status": "down"}]
    assert live.status_code == 200  # liveness unaffected


async def test_dependency_recovers_without_restarting_the_app() -> None:
    server = await serve()
    port = server.sockets[0].getsockname()[1]
    async with running(f"db=127.0.0.1:{port}") as (c, _):
        assert (await c.get("/v1/health/ready")).status_code == 200
        server.close()
        await server.wait_closed()
        assert (await c.get("/v1/health/ready")).status_code == 503
        revived = await serve(port)
        try:
            assert (await c.get("/v1/health/ready")).status_code == 200
        finally:
            revived.close()


async def test_app_starts_while_dependency_is_unreachable() -> None:
    async with running("db=127.0.0.1:1") as (c, _):
        assert (await c.get("/v1/health/live")).status_code == 200


async def test_readiness_is_503_while_shutting_down_and_liveness_stays_ok() -> None:
    async with running() as (c, app):
        app.state.begin_shutdown()  # type: ignore[attr-defined]
        ready = await c.get("/v1/health/ready")
        live = await c.get("/v1/health/live")
    assert ready.status_code == 503 and ready.json() == {"status": "not_ready"}
    assert live.status_code == 200
