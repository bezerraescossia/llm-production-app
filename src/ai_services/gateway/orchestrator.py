"""The gateway: resolves a tier, calls a provider, and normalises the output into events."""

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from typing import Any

from ai_services.gateway.config import GatewayConfig, Tier
from ai_services.gateway.errors import UnknownTierError
from ai_services.gateway.limits import resolve_generation
from ai_services.gateway.providers.base import Provider, ProviderChunk
from ai_services.gateway.types import (
    Completion,
    CompletionRequest,
    FinishReason,
)

Event = tuple[str, dict[str, Any]]


class CompletionStream:
    """A stream whose first event already exists, so earlier failures can still be HTTP errors."""

    def __init__(
        self,
        first: Event,
        events: AsyncGenerator[Event, None],
        *,
        model: str,
        attempts: int,
        fallback_used: bool,
    ) -> None:
        self.first = first
        self._events = events
        self.model = model
        self.attempts = attempts
        self.fallback_used = fallback_used

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Event]:
        yield self.first
        async for event in self._events:
            yield event

    async def aclose(self) -> None:
        await self._events.aclose()


async def _events(chunks: AsyncGenerator[ProviderChunk, None]) -> AsyncGenerator[Event, None]:
    """token... then one usage then one done, whatever order the provider sent finish and usage."""
    index = 0
    finish: FinishReason = "stop"
    usage: tuple[int | None, int | None] = (None, None)
    async with aclosing(chunks):
        async for chunk in chunks:
            if chunk.text is not None:
                yield "token", {"index": index, "text": chunk.text}
                index += 1
            elif chunk.finish_reason is not None:
                finish = chunk.finish_reason
            elif chunk.usage is not None:
                usage = chunk.usage
    yield "usage", {"input_tokens": usage[0], "output_tokens": usage[1], "cost_usd": None}
    yield "done", {"finish_reason": finish}


class Gateway:
    def __init__(self, config: GatewayConfig, providers: Mapping[str, Provider]) -> None:
        self._config = config
        self._providers = providers

    @property
    def config(self) -> GatewayConfig:
        return self._config

    @property
    def default_tier(self) -> str:
        return self._config.default_tier

    def _tier(self, name: str) -> Tier:
        try:
            return self._config.tiers[name]
        except KeyError:
            raise UnknownTierError(name) from None

    async def open(self, request: CompletionRequest) -> CompletionStream:
        tier = self._tier(request.tier)
        candidate = tier.models[0]
        provider = self._providers[candidate.provider]
        settings = resolve_generation(tier.generation, request.settings)
        chunks = provider.stream(candidate.model_id, request.messages, settings)
        events = _events(chunks)
        first = await anext(events)
        return CompletionStream(
            first, events, model=candidate.name, attempts=1, fallback_used=False
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[Event]:
        completion = await self.open(request)
        try:
            async for event in completion:
                yield event
        finally:
            await completion.aclose()

    async def complete(self, request: CompletionRequest) -> Completion:
        completion = await self.open(request)
        text: list[str] = []
        finish: FinishReason = "stop"
        tokens: tuple[int | None, int | None] = (None, None)
        try:
            async for kind, payload in completion:
                if kind == "token":
                    text.append(payload["text"])
                elif kind == "usage":
                    tokens = (payload["input_tokens"], payload["output_tokens"])
                elif kind == "done":
                    finish = payload["finish_reason"]
        finally:
            await completion.aclose()
        return Completion(
            text="".join(text),
            finish_reason=finish,
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            model=completion.model,
            attempts=completion.attempts,
            fallback_used=completion.fallback_used,
        )
