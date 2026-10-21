import asyncio
import time

import pytest

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.stub import PLACEHOLDER_TEXT, StubProvider
from ai_services.gateway.types import GenerationSettings
from tests.unit.gateway.helpers import SETTINGS, USER_MESSAGES, collect


def texts(chunks: list) -> list[str]:  # type: ignore[type-arg]
    return [c.text for c in chunks if c.text is not None]


async def run(model: str, provider: StubProvider | None = None, settings=SETTINGS):  # type: ignore[no-untyped-def]
    return await collect((provider or StubProvider()).stream(model, USER_MESSAGES, settings))


async def test_default_yields_the_placeholder_word_by_word_then_finish_then_usage() -> None:
    chunks = await run("default")
    assert "".join(texts(chunks)) == PLACEHOLDER_TEXT
    assert len(texts(chunks)) == len(PLACEHOLDER_TEXT.split(" "))
    assert chunks[-2].finish_reason == "stop"
    assert chunks[-1].usage == (0, 0)


async def test_empty_has_no_text() -> None:
    chunks = await run("empty")
    assert texts(chunks) == []
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["stop"]
    assert chunks[-1].usage is not None


async def test_blocked_finishes_with_blocked_and_no_text() -> None:
    chunks = await run("blocked")
    assert texts(chunks) == []
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["blocked"]


@pytest.mark.parametrize(
    ("model", "category"),
    [
        ("fail-temporary", ProviderCategory.TEMPORARY),
        ("fail-rate-limited", ProviderCategory.RATE_LIMITED),
        ("fail-timeout", ProviderCategory.TIMEOUT),
        ("fail-unavailable", ProviderCategory.UNAVAILABLE),
        ("fail-auth", ProviderCategory.AUTH),
        ("fail-context", ProviderCategory.CONTEXT_TOO_LARGE),
        ("fail-invalid", ProviderCategory.INVALID_REQUEST),
    ],
)
async def test_failure_models_raise_before_any_output(
    model: str, category: ProviderCategory
) -> None:
    seen: list = []  # type: ignore[type-arg]
    with pytest.raises(ProviderError) as exc:
        async for chunk in StubProvider().stream(model, USER_MESSAGES, SETTINGS):
            seen.append(chunk)
    assert exc.value.category is category
    assert seen == []


async def test_midstream_failure_emits_some_text_then_raises() -> None:
    seen: list = []  # type: ignore[type-arg]
    with pytest.raises(ProviderError) as exc:
        async for chunk in StubProvider().stream("fail-midstream", USER_MESSAGES, SETTINGS):
            seen.append(chunk)
    assert len(texts(seen)) == 2 and exc.value.category is ProviderCategory.TEMPORARY


async def test_slow_delays_each_piece() -> None:
    start = time.perf_counter()
    await run("slow")
    assert time.perf_counter() - start >= 0.2


async def test_stall_never_produces_output() -> None:
    stream = StubProvider().stream("stall", USER_MESSAGES, SETTINGS)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.1)
    await stream.aclose()


async def test_stall_midstream_produces_one_piece_then_hangs() -> None:
    stream = StubProvider().stream("stall-midstream", USER_MESSAGES, SETTINGS)
    first = await asyncio.wait_for(anext(stream), 0.5)
    assert first.text
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), 0.1)
    await stream.aclose()


async def test_max_output_tokens_cuts_the_answer_with_length() -> None:
    chunks = await run("default", settings=GenerationSettings(max_output_tokens=3, temperature=0.3))
    assert len(texts(chunks)) == 3
    assert [c.finish_reason for c in chunks if c.finish_reason] == ["length"]


async def test_default_honors_delay_and_the_fail_after_hook() -> None:
    start = time.perf_counter()
    await run("default", StubProvider(delay_ms=20))
    assert time.perf_counter() - start >= 0.15

    seen: list = []  # type: ignore[type-arg]
    with pytest.raises(RuntimeError, match="injected fault"):
        async for chunk in StubProvider(fail_after=lambda: 2).stream(
            "default", USER_MESSAGES, SETTINGS
        ):
            seen.append(chunk)
    assert len(texts(seen)) == 2


async def test_closing_early_is_observed_by_the_stub() -> None:
    provider = StubProvider()
    stream = provider.stream("default", USER_MESSAGES, SETTINGS)
    await anext(stream)
    assert provider.active == 1
    await stream.aclose()
    assert provider.active == 0 and provider.closed == 1


async def test_unknown_stub_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="nope"):
        await run("nope")
