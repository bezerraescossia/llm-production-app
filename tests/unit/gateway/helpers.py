"""Test doubles and builders shared by the gateway tests."""

from collections.abc import AsyncGenerator, AsyncIterator, Sequence

from ai_services.gateway.providers.base import ProviderChunk
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
