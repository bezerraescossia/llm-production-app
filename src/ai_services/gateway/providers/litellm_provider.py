"""The only module that imports LiteLLM: real provider calls, normalised to ProviderChunk."""

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any, cast

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadGatewayError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.base import ProviderChunk
from ai_services.gateway.types import FinishReason, GenerationSettings
from ai_services.schemas import Message

CompletionCall = Callable[..., Awaitable[AsyncIterator[Any]]]

_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "blocked",
}

# Order matters: specific classes first, because several are subclasses of the generic ones.
_CLASSIFICATION: list[tuple[type[BaseException], ProviderCategory]] = [
    (ContextWindowExceededError, ProviderCategory.CONTEXT_TOO_LARGE),
    (ContentPolicyViolationError, ProviderCategory.CONTENT_BLOCKED),
    (Timeout, ProviderCategory.TIMEOUT),
    (RateLimitError, ProviderCategory.RATE_LIMITED),
    (AuthenticationError, ProviderCategory.AUTH),
    (PermissionDeniedError, ProviderCategory.AUTH),
    (ServiceUnavailableError, ProviderCategory.UNAVAILABLE),
    (NotFoundError, ProviderCategory.UNAVAILABLE),
    (BadRequestError, ProviderCategory.INVALID_REQUEST),
    (UnprocessableEntityError, ProviderCategory.INVALID_REQUEST),
    (InternalServerError, ProviderCategory.TEMPORARY),
    (BadGatewayError, ProviderCategory.TEMPORARY),
    (APIConnectionError, ProviderCategory.TEMPORARY),
    (APIError, ProviderCategory.TEMPORARY),
]


def classify(exc: BaseException) -> ProviderError | None:
    """Map a LiteLLM exception to a ProviderError, or None if it is not a provider failure."""
    for exc_type, category in _CLASSIFICATION:
        if isinstance(exc, exc_type):
            return ProviderError(category, retry_after_seconds=_retry_after(exc))
    return None


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    value = getattr(getattr(response, "headers", None), "get", lambda _k: None)("retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class LiteLLMProvider:
    def __init__(
        self, provider: str, api_key: str | None, completion: CompletionCall | None = None
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._completion: CompletionCall = completion or cast(CompletionCall, litellm.acompletion)

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        kwargs: dict[str, Any] = {
            "model": f"{self._provider}/{model_id}",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "api_key": self._api_key,
            "max_tokens": settings.max_output_tokens,
            "temperature": settings.temperature,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds

        finish: FinishReason = "stop"
        usage: tuple[int | None, int | None] = (None, None)
        upstream: AsyncIterator[Any] | None = None
        try:
            upstream = await self._completion(**kwargs)
            async for raw in upstream:
                for choice in raw.choices or []:
                    text = getattr(choice.delta, "content", None)
                    if text:
                        yield ProviderChunk(text=text)
                    if choice.finish_reason is not None:
                        finish = _FINISH_REASONS.get(choice.finish_reason, "stop")
                if raw.usage is not None:
                    usage = (raw.usage.prompt_tokens, raw.usage.completion_tokens)
        except Exception as exc:
            mapped = classify(exc)
            if mapped is None:
                raise
            raise mapped from None
        finally:
            closer = getattr(upstream, "aclose", None)
            if closer is not None:
                await closer()
        yield ProviderChunk(finish_reason=finish)
        yield ProviderChunk(usage=usage)
