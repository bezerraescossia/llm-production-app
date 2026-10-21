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
    UnsupportedParamsError,
)
from litellm.utils import get_optional_params

from ai_services.gateway.errors import ProviderCategory, ProviderError
from ai_services.gateway.providers.base import ProviderChunk
from ai_services.gateway.types import FinishReason, GenerationSettings
from ai_services.schemas import Message

CompletionCall = Callable[..., Awaitable[AsyncIterator[Any]]]
ParamsCheck = Callable[[str, str], set[str]]

# Probe values: anything other than the one value some models insist on (temperature 1).
_PROBES: dict[str, Any] = {"temperature": 0.5, "max_tokens": 100}

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


def is_known_model(provider: str, model_id: str) -> bool:
    """True if the library's (version-pinned, local) model map knows this model."""
    return model_id in litellm.model_cost or f"{provider}/{model_id}" in litellm.model_cost


def default_params_check(provider: str, model_id: str) -> set[str]:
    """Names of generation parameters this model does not accept (asked of the library itself).

    Some models (the Claude 5.5 and GPT-5 families) accept only their default temperature, and
    the library raises for any other value, so those parameters are dropped explicitly.
    """
    dropped: set[str] = set()
    for name, probe in _PROBES.items():
        try:
            get_optional_params(model=model_id, custom_llm_provider=provider, **{name: probe})
        except UnsupportedParamsError:
            dropped.add(name)
        except Exception:  # noqa: BLE001 - an unmapped model is not a reason to drop anything
            continue
    return dropped


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
        self,
        provider: str,
        api_key: str | None,
        completion: CompletionCall | None = None,
        params_check: ParamsCheck | None = None,
    ) -> None:
        self._provider = provider
        self._api_key = api_key
        self._params_check = params_check or default_params_check
        self._dropped: dict[str, set[str]] = {}
        self._completion: CompletionCall = completion or cast(CompletionCall, litellm.acompletion)

    def dropped_params(self, model_id: str) -> set[str]:
        """Generation parameters to omit for this model (computed once, then cached)."""
        if model_id not in self._dropped:
            self._dropped[model_id] = set(self._params_check(self._provider, model_id))
        return self._dropped[model_id]

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
        }
        dropped = self.dropped_params(model_id)
        if "max_tokens" not in dropped:
            kwargs["max_tokens"] = settings.max_output_tokens
        if "temperature" not in dropped:
            kwargs["temperature"] = settings.temperature
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
