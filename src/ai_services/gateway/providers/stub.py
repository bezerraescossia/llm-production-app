"""Deterministic stub provider: works with no credentials and injects faults on demand.

The model id picks the behavior (see research R10), so a tier such as
`[stub/fail-temporary, stub/default]` demonstrates fallback end to end, offline.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.base import ProviderChunk
from ai_services.gateway.types import GenerationSettings
from ai_services.schemas import Message

PLACEHOLDER_TEXT = "This is a placeholder answer from the AI-services foundation."
SLOW_DELAY_MS = 30
_NEVER_SECONDS = 3600.0

_FAILURES: dict[str, tuple[ProviderCategory, float | None]] = {
    "fail-temporary": (ProviderCategory.TEMPORARY, None),
    "fail-rate-limited": (ProviderCategory.RATE_LIMITED, 0.01),
    "fail-timeout": (ProviderCategory.TIMEOUT, None),
    "fail-unavailable": (ProviderCategory.UNAVAILABLE, None),
    "fail-auth": (ProviderCategory.AUTH, None),
    "fail-context": (ProviderCategory.CONTEXT_TOO_LARGE, None),
    "fail-invalid": (ProviderCategory.INVALID_REQUEST, None),
}
_ANSWERING = {"default", "slow", "fail-midstream", "stall-midstream"}
STUB_MODELS = frozenset({*_FAILURES, *_ANSWERING, "empty", "blocked", "stall"})


def _pieces() -> list[str]:
    words = PLACEHOLDER_TEXT.split(" ")
    return [w if i == len(words) - 1 else w + " " for i, w in enumerate(words)]


class StubProvider:
    def __init__(
        self,
        delay_ms: int = 0,
        fail_after: Callable[[], int | None] | None = None,
    ) -> None:
        self._delay_ms = delay_ms
        self._fail_after = fail_after
        self.active = 0  # streams currently open
        self.closed = 0  # streams that have been closed (finished or cancelled)

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        self.active += 1
        try:
            async for chunk in self._script(model_id, settings):
                yield chunk
        finally:
            self.active -= 1
            self.closed += 1

    async def _script(
        self, model: str, settings: GenerationSettings
    ) -> AsyncGenerator[ProviderChunk, None]:
        if model not in STUB_MODELS:
            raise ValueError(f"unknown stub model {model!r}")
        if model in _FAILURES:
            category, retry_after = _FAILURES[model]
            raise ProviderError(category, retry_after_seconds=retry_after)
        if model == "stall":
            await asyncio.sleep(_NEVER_SECONDS)
        if model == "empty":
            yield ProviderChunk(finish_reason="stop")
            yield ProviderChunk(usage=(0, 0))
            return
        if model == "blocked":
            yield ProviderChunk(finish_reason="blocked")
            yield ProviderChunk(usage=(0, 0))
            return

        delay = SLOW_DELAY_MS if model == "slow" else self._delay_ms
        fail_after = self._fail_after() if (self._fail_after and model == "default") else None
        pieces = _pieces()
        limit = settings.max_output_tokens
        emitted = 0
        for piece in pieces:
            if limit is not None and emitted >= limit:
                break
            if fail_after is not None and emitted >= fail_after:
                raise RuntimeError("injected fault")
            if model == "fail-midstream" and emitted == 2:
                raise ProviderError(ProviderCategory.TEMPORARY)
            if delay:
                await asyncio.sleep(delay / 1000)
            yield ProviderChunk(text=piece)
            emitted += 1
            if model == "stall-midstream":
                await asyncio.sleep(_NEVER_SECONDS)
        cut = limit is not None and emitted < len(pieces)
        yield ProviderChunk(finish_reason="length" if cut else "stop")
        yield ProviderChunk(usage=(0, 0))
