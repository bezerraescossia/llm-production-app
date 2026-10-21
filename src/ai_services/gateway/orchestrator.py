"""The gateway: tier selection, attempts, retries, in-tier fallback and event normalisation."""

import asyncio
import random
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing
from typing import Any

from ai_services.errors import ErrorCode
from ai_services.gateway.config import GatewayConfig, ModelCandidate, Tier
from ai_services.gateway.cooldown import FailureCooldown, counts_toward_cooldown
from ai_services.gateway.errors import (
    GatewayError,
    ProviderCategory,
    ProviderError,
    UnknownTierError,
    error_for_failures,
)
from ai_services.gateway.limits import models_that_fit, resolve_generation
from ai_services.gateway.logging import log_attempt_failed, log_completion_finished
from ai_services.gateway.providers.base import Provider, ProviderChunk
from ai_services.gateway.types import Completion, CompletionRequest, FinishReason

Event = tuple[str, dict[str, Any]]

_RETRY = {ProviderCategory.TEMPORARY, ProviderCategory.RATE_LIMITED, ProviderCategory.TIMEOUT}
_NEXT_MODEL = {
    ProviderCategory.UNAVAILABLE,
    ProviderCategory.AUTH,
    ProviderCategory.CONTEXT_TOO_LARGE,
}
_MAX_RETRY_AFTER_SECONDS = 5.0
_DEADLINE_SLACK_SECONDS = 0.002


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
        tier: str,
        started: float,
        first_output_ms: float,
        inner: AsyncGenerator[Event, None] | None = None,
    ) -> None:
        self.first = first
        self._events = events
        self._tier = tier
        self._started = started
        self._first_output_ms = first_output_ms
        self._tokens: tuple[int | None, int | None] = (None, None)
        self._finish_reason: str | None = None
        self._summarised = False
        self._inner = inner  # closed too, because a wrapper that never started cannot close it
        self.model = model
        self.attempts = attempts
        self.fallback_used = fallback_used

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Event]:
        try:
            self._observe(self.first)
            yield self.first
            async for event in self._events:
                self._observe(event)
                yield event
        finally:
            self._summarise()

    def _observe(self, event: Event) -> None:
        kind, payload = event
        if kind == "usage":
            self._tokens = (payload["input_tokens"], payload["output_tokens"])
        elif kind == "done":
            self._finish_reason = payload["finish_reason"]
        elif kind == "error":
            self._finish_reason = "error"

    def _summarise(self) -> None:
        """One content-free summary per completion; a stream closed early counts as cancelled."""
        if self._summarised:
            return
        self._summarised = True
        total_ms = (asyncio.get_running_loop().time() - self._started) * 1000
        log_completion_finished(
            tier=self._tier,
            model=self.model,
            attempts=self.attempts,
            fallback_used=self.fallback_used,
            first_output_ms=self._first_output_ms,
            total_ms=total_ms,
            finish_reason=self._finish_reason or "cancelled",
            input_tokens=self._tokens[0],
            output_tokens=self._tokens[1],
        )

    async def aclose(self) -> None:
        await self._events.aclose()
        if self._inner is not None:
            await self._inner.aclose()
        self._summarise()


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


async def _only(event: Event) -> AsyncGenerator[Event, None]:
    yield event


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        providers: Mapping[str, Provider],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        clock: Callable[[], float] = time.monotonic,
        input_limit: Callable[[ModelCandidate], int | None] | None = None,
    ) -> None:
        self._config = config
        self._providers = providers
        self._sleep = sleep
        self._uniform = uniform
        self._cooldown = FailureCooldown(config.cooldown, clock=clock)
        self._input_limit = input_limit or (lambda m: m.max_input_tokens)

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

    def _order(self, models: list[ModelCandidate]) -> list[ModelCandidate]:
        """Configured order, skipping models that are cooling down; if all are, the soonest."""
        available = [m for m in models if not self._cooldown.is_cooling(m.name)]
        if available:
            return available
        soonest = self._cooldown.soonest([m.name for m in models])
        return [m for m in models if m.name == soonest][:1]

    def _backoff(self, attempt: int, err: ProviderError) -> float:
        if err.retry_after_seconds is not None:
            return min(err.retry_after_seconds, _MAX_RETRY_AFTER_SECONDS)
        policy = self._config.retry
        ceiling = min(policy.backoff_max_seconds, policy.backoff_base_seconds * 2 ** (attempt - 1))
        return self._uniform(0.0, ceiling)

    async def open(self, request: CompletionRequest) -> CompletionStream:
        tier = self._tier(request.tier)
        settings = resolve_generation(tier.generation, request.settings)
        fitting = models_that_fit(tier.models, request.messages, self._input_limit)
        if not fitting:
            raise GatewayError(ErrorCode.INPUT_TOO_LARGE)

        timeouts = self._config.timeouts
        loop = asyncio.get_running_loop()
        started = loop.time()
        total_deadline = started + timeouts.total_seconds
        # The overall wait for the first output (across attempts, retries, backoff and fallbacks).
        wait_deadline = min(started + timeouts.pre_output_seconds, total_deadline)

        attempts = 0
        failures: list[ProviderCategory] = []
        for candidate in self._order(fitting):
            provider = self._providers[candidate.provider]
            for attempt in range(1, self._config.retry.max_attempts_per_model + 1):
                remaining = wait_deadline - loop.time()
                if remaining <= 0:
                    raise GatewayError(ErrorCode.UPSTREAM_TIMEOUT)
                limit = min(timeouts.first_output_seconds, remaining)
                attempts += 1
                events = _events(
                    provider.stream(
                        candidate.model_id, request.messages, settings, timeout_seconds=limit
                    )
                )
                try:
                    async with asyncio.timeout(limit):
                        first = await anext(events)
                except (ProviderError, TimeoutError) as raised:
                    await events.aclose()
                    if isinstance(raised, TimeoutError):
                        log_attempt_failed(
                            model=candidate.name,
                            category=ProviderCategory.TIMEOUT.value,
                            attempt=attempt,
                        )
                        if loop.time() >= wait_deadline - _DEADLINE_SLACK_SECONDS:
                            raise GatewayError(ErrorCode.UPSTREAM_TIMEOUT) from None
                        err = ProviderError(ProviderCategory.TIMEOUT)
                    else:
                        err = raised
                        log_attempt_failed(
                            model=candidate.name, category=err.category.value, attempt=attempt
                        )
                    failures.append(err.category)
                    if counts_toward_cooldown(err.category):
                        self._cooldown.record_failure(candidate.name)
                    if err.category is ProviderCategory.CONTENT_BLOCKED:
                        # A safety block is never retried and never routed around.
                        blocked: Event = (
                            "usage",
                            {"input_tokens": None, "output_tokens": None, "cost_usd": None},
                        )
                        rest = _only(("done", {"finish_reason": "blocked"}))
                        return CompletionStream(
                            blocked,
                            rest,
                            model=candidate.name,
                            attempts=attempts,
                            fallback_used=candidate.name != tier.models[0].name,
                            tier=request.tier,
                            started=started,
                            first_output_ms=(loop.time() - started) * 1000,
                        )
                    if err.category is ProviderCategory.INVALID_REQUEST:
                        raise GatewayError(ErrorCode.UPSTREAM_ERROR) from None
                    if err.category in _NEXT_MODEL or err.category not in _RETRY:
                        break
                    if self._cooldown.is_cooling(candidate.name):
                        break
                    if attempt == self._config.retry.max_attempts_per_model:
                        break
                    pause = min(self._backoff(attempt, err), wait_deadline - loop.time())
                    if pause <= 0:
                        raise GatewayError(ErrorCode.UPSTREAM_TIMEOUT) from None
                    await self._sleep(pause)
                    continue
                self._cooldown.record_success(candidate.name)
                return CompletionStream(
                    first,
                    self._guard(events, candidate.name, total_deadline),
                    model=candidate.name,
                    attempts=attempts,
                    fallback_used=candidate.name != tier.models[0].name,
                    tier=request.tier,
                    started=started,
                    first_output_ms=(loop.time() - started) * 1000,
                    inner=events,
                )
        raise error_for_failures(failures)

    async def _guard(
        self, events: AsyncGenerator[Event, None], model: str, total_deadline: float
    ) -> AsyncGenerator[Event, None]:
        """After the first piece nothing is retried or replaced: a failure or a limit ends it."""
        loop = asyncio.get_running_loop()
        idle = self._config.timeouts.idle_seconds
        async with aclosing(events):
            while True:
                limit = min(idle, total_deadline - loop.time())
                try:
                    if limit <= 0:
                        raise TimeoutError
                    async with asyncio.timeout(limit):
                        event = await anext(events)
                except StopAsyncIteration:
                    return
                except (ProviderError, TimeoutError) as raised:
                    category = (
                        raised.category
                        if isinstance(raised, ProviderError)
                        else ProviderCategory.TIMEOUT
                    )
                    log_attempt_failed(model=model, category=category.value, midstream=True)
                    if counts_toward_cooldown(category):
                        self._cooldown.record_failure(model)
                    final = error_for_failures([category])
                    yield "error", {"code": final.code.value, "message": final.message}
                    return
                yield event

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
                elif kind == "error":
                    raise GatewayError(ErrorCode(payload["code"]))
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
