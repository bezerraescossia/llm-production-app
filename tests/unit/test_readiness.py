import asyncio
import time
from collections.abc import AsyncIterator

import pytest

from ai_services.config import Dependency
from ai_services.readiness import check_dependencies, check_dependency, overall_status


@pytest.fixture
async def open_port() -> AsyncIterator[int]:
    async def handler(_r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        w.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()


async def test_open_port_is_up(open_port: int) -> None:
    assert await check_dependency(Dependency(name="x", host="127.0.0.1", port=open_port)) is True


async def test_closed_port_is_down_within_one_second() -> None:
    start = time.perf_counter()
    assert await check_dependency(Dependency(name="x", host="127.0.0.1", port=1)) is False
    assert time.perf_counter() - start < 1.0


async def test_unroutable_host_times_out_within_one_second() -> None:
    start = time.perf_counter()
    assert await check_dependency(Dependency(name="x", host="10.255.255.1", port=9)) is False
    assert time.perf_counter() - start < 1.5


async def test_overall_ready_only_if_every_dependency_up(open_port: int) -> None:
    up = Dependency(name="up", host="127.0.0.1", port=open_port)
    down = Dependency(name="down", host="127.0.0.1", port=1)
    results = await check_dependencies([up, down])
    assert [(r.name, r.status) for r in results] == [("up", "up"), ("down", "down")]
    assert overall_status(results) == "not_ready"
    assert overall_status(await check_dependencies([up])) == "ready"


async def test_empty_dependency_list_is_ready() -> None:
    results = await check_dependencies([])
    assert results == [] and overall_status(results) == "ready"
