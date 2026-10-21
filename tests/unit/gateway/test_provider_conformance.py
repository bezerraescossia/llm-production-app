"""One shared test body run against the stub and the LiteLLM adapter (SC-001)."""

import asyncio
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from litellm import exceptions as llm_exc

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.base import Provider, ProviderChunk
from ai_services.gateway.providers.litellm_provider import LiteLLMProvider
from ai_services.gateway.providers.stub import PLACEHOLDER_TEXT, StubProvider
from tests.unit.gateway.helpers import SETTINGS, USER_MESSAGES, collect

PIECES = [word + " " for word in PLACEHOLDER_TEXT.split(" ")[:-1]] + [
    PLACEHOLDER_TEXT.split(" ")[-1]
]


def content_chunk(text: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=None)],
        usage=None,
    )


def finish_chunk(reason: str | None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=reason)],
        usage=None,
    )


def usage_chunk(prompt: int, completion: int) -> Any:
    return SimpleNamespace(
        choices=[], usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    )


class FakeCompletion:
    """Stands in for litellm.acompletion: records the call and returns a scripted stream."""

    def __init__(self, chunks: list[Any] | None = None, error: BaseException | None = None) -> None:
        self.chunks = chunks if chunks is not None else self.normal()
        self.error = error
        self.kwargs: dict[str, Any] = {}
        self.upstream_closed = False

    @staticmethod
    def normal(finish: str | None = "stop", usage: bool = True) -> list[Any]:
        out = [content_chunk(p) for p in PIECES] + [finish_chunk(finish)]
        return out + ([usage_chunk(8, 2)] if usage else [])

    async def __call__(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error

        async def gen() -> AsyncIterator[Any]:
            try:
                for chunk in self.chunks:
                    yield chunk
            finally:
                self.upstream_closed = True

        return gen()


def litellm_provider(fake: FakeCompletion) -> LiteLLMProvider:
    return LiteLLMProvider(
        "openai", api_key="sk-test-key", completion=fake, params_check=lambda p, m: set()
    )


def summarize(
    chunks: list[ProviderChunk],
) -> tuple[str, list[str], list[tuple[int | None, int | None]]]:
    text = "".join(c.text for c in chunks if c.text is not None)
    finishes = [c.finish_reason for c in chunks if c.finish_reason is not None]
    usages = [c.usage for c in chunks if c.usage is not None]
    return text, finishes, usages


def kinds(chunks: list[ProviderChunk]) -> list[str]:
    return [
        "text" if c.text is not None else "finish" if c.finish_reason else "usage" for c in chunks
    ]


PROVIDERS: dict[str, Callable[[], tuple[Provider, str]]] = {
    "stub": lambda: (StubProvider(), "default"),
    "litellm": lambda: (litellm_provider(FakeCompletion()), "gpt-5-nano-2025-08-07"),
}


@pytest.mark.parametrize("name", PROVIDERS)
async def test_every_provider_yields_the_same_normalised_shape(name: str) -> None:
    provider, model = PROVIDERS[name]()
    chunks = await collect(provider.stream(model, USER_MESSAGES, SETTINGS))
    text, finishes, usages = summarize(chunks)
    assert text == PLACEHOLDER_TEXT
    assert finishes == ["stop"] and len(usages) == 1
    order = kinds(chunks)
    assert order == ["text"] * len(PIECES) + ["finish", "usage"]


async def test_litellm_call_is_made_with_streaming_usage_key_and_limits() -> None:
    fake = FakeCompletion()
    await collect(
        litellm_provider(fake).stream(
            "gpt-5-nano-2025-08-07", USER_MESSAGES, SETTINGS, timeout_seconds=7.5
        )
    )
    kw = fake.kwargs
    assert kw["model"] == "openai/gpt-5-nano-2025-08-07"
    assert kw["stream"] is True and kw["stream_options"] == {"include_usage": True}
    assert kw["api_key"] == "sk-test-key"
    assert kw["max_tokens"] == 100 and kw["temperature"] == 0.3 and kw["timeout"] == 7.5
    assert kw["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.parametrize(
    ("provider_reason", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "blocked"),
        ("tool_calls", "stop"),
        (None, "stop"),
    ],
)
async def test_finish_reasons_are_mapped(provider_reason: str | None, expected: str) -> None:
    fake = FakeCompletion(FakeCompletion.normal(finish=provider_reason))
    chunks = await collect(litellm_provider(fake).stream("m", USER_MESSAGES, SETTINGS))
    assert summarize(chunks)[1] == [expected]


async def test_usage_is_taken_from_the_final_chunk_and_missing_usage_is_unknown() -> None:
    with_usage = await collect(
        litellm_provider(FakeCompletion()).stream("m", USER_MESSAGES, SETTINGS)
    )
    assert summarize(with_usage)[2] == [(8, 2)]
    without = FakeCompletion(FakeCompletion.normal(usage=False))
    chunks = await collect(litellm_provider(without).stream("m", USER_MESSAGES, SETTINGS))
    assert summarize(chunks)[2] == [(None, None)]


async def test_closing_the_adapter_closes_the_upstream_stream() -> None:
    fake = FakeCompletion()
    stream = litellm_provider(fake).stream("m", USER_MESSAGES, SETTINGS)
    await anext(stream)
    await stream.aclose()
    assert fake.upstream_closed


def make_response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://provider.test"))


def lite(cls: type, **extra: Any) -> BaseException:
    return cls(
        message="provider text that must never leak", model="m", llm_provider="openai", **extra
    )


ERROR_CASES: list[tuple[str, Callable[[], BaseException], ProviderCategory]] = [
    ("timeout", lambda: lite(llm_exc.Timeout), ProviderCategory.TIMEOUT),
    ("connection", lambda: lite(llm_exc.APIConnectionError), ProviderCategory.TEMPORARY),
    ("internal", lambda: lite(llm_exc.InternalServerError), ProviderCategory.TEMPORARY),
    ("bad-gateway", lambda: lite(llm_exc.BadGatewayError), ProviderCategory.TEMPORARY),
    ("rate-limit", lambda: lite(llm_exc.RateLimitError), ProviderCategory.RATE_LIMITED),
    ("unavailable", lambda: lite(llm_exc.ServiceUnavailableError), ProviderCategory.UNAVAILABLE),
    ("not-found", lambda: lite(llm_exc.NotFoundError), ProviderCategory.UNAVAILABLE),
    ("auth", lambda: lite(llm_exc.AuthenticationError), ProviderCategory.AUTH),
    (
        "permission",
        lambda: lite(llm_exc.PermissionDeniedError, response=make_response(403)),
        ProviderCategory.AUTH,
    ),
    (
        "context",
        lambda: lite(llm_exc.ContextWindowExceededError),
        ProviderCategory.CONTEXT_TOO_LARGE,
    ),
    ("policy", lambda: lite(llm_exc.ContentPolicyViolationError), ProviderCategory.CONTENT_BLOCKED),
    ("bad-request", lambda: lite(llm_exc.BadRequestError), ProviderCategory.INVALID_REQUEST),
    (
        "unprocessable",
        lambda: lite(llm_exc.UnprocessableEntityError, response=make_response(422)),
        ProviderCategory.INVALID_REQUEST,
    ),
]


@pytest.mark.parametrize(("name", "make", "category"), ERROR_CASES, ids=[c[0] for c in ERROR_CASES])
async def test_litellm_exceptions_map_to_categories_without_provider_text(
    name: str, make: Callable[[], BaseException], category: ProviderCategory
) -> None:
    provider = litellm_provider(FakeCompletion(error=make()))
    with pytest.raises(ProviderError) as exc:
        await collect(provider.stream("m", USER_MESSAGES, SETTINGS))
    assert exc.value.category is category
    assert "must never leak" not in str(exc.value)


async def test_failure_while_streaming_is_mapped_too() -> None:
    class Broken(FakeCompletion):
        async def __call__(self, **kwargs: Any) -> AsyncIterator[Any]:
            async def gen() -> AsyncIterator[Any]:
                yield content_chunk("hi ")
                raise lite(llm_exc.InternalServerError)

            return gen()

    seen: list[ProviderChunk] = []
    with pytest.raises(ProviderError) as exc:
        async for chunk in litellm_provider(Broken()).stream("m", USER_MESSAGES, SETTINGS):
            seen.append(chunk)
    assert seen[0].text == "hi " and exc.value.category is ProviderCategory.TEMPORARY


async def test_cancellation_is_never_swallowed() -> None:
    provider = litellm_provider(FakeCompletion(error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await collect(provider.stream("m", USER_MESSAGES, SETTINGS))


async def test_unexpected_exceptions_are_not_disguised_as_provider_errors() -> None:
    provider = litellm_provider(FakeCompletion(error=RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        await collect(provider.stream("m", USER_MESSAGES, SETTINGS))
