"""SC-006: the gateway adds at most 50 ms (p95, 20 concurrent) over calling the stub directly.

Timing-sensitive by nature; the 50 ms margin is far above the real overhead (well under 1 ms), so a
failure here means a genuine regression, not noise.
"""

import asyncio
import time

from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig
from ai_services.gateway.providers.stub import StubProvider
from ai_services.gateway.types import CompletionRequest, GenerationSettings
from tests.unit.gateway.helpers import USER_MESSAGES

CONCURRENCY = 20
ROUNDS = 5
MARGIN_SECONDS = 0.050


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


async def first_output_direct(stub: StubProvider) -> float:
    started = time.perf_counter()
    stream = stub.stream("default", USER_MESSAGES, GenerationSettings(100, 0.3))
    await anext(stream)
    elapsed = time.perf_counter() - started
    await stream.aclose()
    return elapsed


async def first_output_via_gateway(gateway: Gateway) -> float:
    started = time.perf_counter()
    stream = await gateway.open(CompletionRequest("medium", USER_MESSAGES))
    elapsed = time.perf_counter() - started
    await stream.aclose()
    return elapsed


async def test_the_gateway_adds_no_more_than_fifty_milliseconds_at_p95() -> None:
    stub = StubProvider()
    gateway = Gateway(GatewayConfig.default(), {"stub": stub})
    direct: list[float] = []
    through: list[float] = []
    for _ in range(ROUNDS):
        direct += await asyncio.gather(*(first_output_direct(stub) for _ in range(CONCURRENCY)))
        through += await asyncio.gather(
            *(first_output_via_gateway(gateway) for _ in range(CONCURRENCY))
        )
    assert p95(through) - p95(direct) <= MARGIN_SECONDS
