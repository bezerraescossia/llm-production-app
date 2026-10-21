"""Test doubles and builders shared by the gateway tests."""

from collections.abc import AsyncGenerator, AsyncIterator, Sequence

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.base import ProviderChunk
from ai_services.gateway.providers.stub import StubProvider
from ai_services.gateway.types import GenerationSettings
from ai_services.schemas import Message

USER_MESSAGES = [Message(role="user", content="hello")]
SETTINGS = GenerationSettings(max_output_tokens=100, temperature=0.3)


async def collect(stream: AsyncIterator[ProviderChunk]) -> list[ProviderChunk]:
    return [chunk async for chunk in stream]


class ScriptedProvider:
    """Yields the chunks it is given and counts calls and closes."""

    def __init__(self, chunks: Sequence[ProviderChunk]) -> None:
        self.chunks = list(chunks)
        self.calls = 0
        self.closed = 0

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        self.calls += 1
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed += 1


class RecordingStub(StubProvider):
    """A stub that records every model id it is asked to stream, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        self.calls.append(model_id)
        async for chunk in super().stream(
            model_id, messages, settings, timeout_seconds=timeout_seconds
        ):
            yield chunk


class RaisingProvider:
    """Raises a classified failure on every call (used for categories the stub cannot raise)."""

    def __init__(
        self, category: ProviderCategory, retry_after_seconds: float | None = None
    ) -> None:
        self.category = category
        self.retry_after_seconds = retry_after_seconds
        self.calls = 0

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        self.calls += 1
        raise ProviderError(self.category, retry_after_seconds=self.retry_after_seconds)
        yield  # pragma: no cover - makes this an async generator


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSleep:
    """Records requested sleeps instead of waiting."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def max_jitter(low: float, high: float) -> float:
    """Deterministic 'random': always the top of the range."""
    return high
