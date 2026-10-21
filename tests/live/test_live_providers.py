"""Real-provider checks. They cost a little money, so they are opt-in.

Run:  ANTHROPIC_API_KEY=... OPENAI_API_KEY=... uv run pytest -m live tests/live -v

A provider's tests are skipped unless its API key is set. Nothing here runs in the default test
run or in CI (the default `addopts` excludes the `live` marker).
"""

import os
import time

import pytest

from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig
from ai_services.gateway.providers.litellm_provider import LiteLLMProvider
from ai_services.gateway.types import CompletionRequest, GenerationSettings
from ai_services.schemas import Message

pytestmark = pytest.mark.live

MODELS = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-5-5"),
    "openai": ("OPENAI_API_KEY", "openai/gpt-5-nano-2025-08-07"),
}


def gateway_for(provider: str) -> Gateway:
    variable, model = MODELS[provider]
    key = os.environ.get(variable)
    if not key:
        pytest.skip(f"{variable} is not set")
    config = GatewayConfig.from_models({t: [model] for t in ("small", "medium", "large")})
    return Gateway(config, {provider: LiteLLMProvider(provider, key)})


def say(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


@pytest.fixture(params=sorted(MODELS))
def gateway(request: pytest.FixtureRequest) -> Gateway:
    return gateway_for(request.param)


async def test_a_short_answer_has_the_normal_event_shape(gateway: Gateway) -> None:
    events = [
        e
        async for e in gateway.stream(
            CompletionRequest("small", say("Reply with the single word: ok"))
        )
    ]
    kinds = [k for k, _ in events]
    assert kinds[-2:] == ["usage", "done"] and set(kinds[:-2]) == {"token"} and kinds[:-2]
    assert events[-1][1]["finish_reason"] == "stop"
    usage = events[-2][1]
    assert usage["input_tokens"] and usage["output_tokens"]  # the provider reported real counts


async def test_the_default_budget_leaves_room_for_a_visible_answer(gateway: Gateway) -> None:
    """Research R13: reasoning models can spend the whole budget thinking and return no text."""
    result = await gateway.complete(
        CompletionRequest("small", say("Reply with the single word: ok"))
    )
    assert result.text.strip(), "the answer was empty; raise the tier's default max_output_tokens"
    assert result.finish_reason == "stop"


async def test_a_tiny_output_limit_finishes_with_length(gateway: Gateway) -> None:
    request = CompletionRequest(
        "small",
        say("Write a very long story about a lighthouse keeper, at least 800 words."),
        GenerationSettings(max_output_tokens=16),
    )
    result = await gateway.complete(request)
    assert result.finish_reason == "length"


async def test_closing_a_stream_early_returns_promptly(gateway: Gateway) -> None:
    request = CompletionRequest("small", say("Count from 1 to 300, one number per line."))
    stream = await gateway.open(request)
    started = time.perf_counter()
    await stream.aclose()
    assert time.perf_counter() - started < 2.0
