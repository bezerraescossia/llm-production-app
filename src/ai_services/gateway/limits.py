"""Generation settings (per-tier defaults and hard ceilings) and the input size check."""

import math
from collections.abc import Callable, Sequence

from ai_services.gateway.config import GenerationLimits, ModelCandidate
from ai_services.gateway.errors import GenerationSettingError
from ai_services.gateway.types import GenerationSettings
from ai_services.schemas import Message

DEFAULT_MAX_INPUT_TOKENS = 100_000
_CHARS_PER_TOKEN = 3  # deliberately pessimistic for English, so the check errs on the safe side


def estimate_tokens(messages: Sequence[Message]) -> int:
    """A cheap, conservative estimate of the input size: total characters over three."""
    return math.ceil(sum(len(m.content) for m in messages) / _CHARS_PER_TOKEN)


def models_that_fit(
    models: Sequence[ModelCandidate],
    messages: Sequence[Message],
    input_limit: Callable[[ModelCandidate], int | None] = lambda m: m.max_input_tokens,
) -> list[ModelCandidate]:
    """The models whose input limit can take the conversation; the messages are never altered."""
    needed = estimate_tokens(messages)
    return [m for m in models if needed <= (input_limit(m) or DEFAULT_MAX_INPUT_TOKENS)]


def resolve_generation(
    limits: GenerationLimits, requested: GenerationSettings
) -> GenerationSettings:
    """Apply tier defaults; a caller may lower a setting but never raise it above the ceiling."""
    tokens = requested.max_output_tokens
    if tokens is None:
        tokens = limits.max_output_tokens.default
    elif tokens > limits.max_output_tokens.ceiling:
        raise GenerationSettingError(
            "max_output_tokens", requested=tokens, ceiling=limits.max_output_tokens.ceiling
        )
    temperature = requested.temperature
    if temperature is None:
        temperature = limits.temperature.default
    elif temperature > limits.temperature.ceiling:
        raise GenerationSettingError(
            "temperature", requested=temperature, ceiling=limits.temperature.ceiling
        )
    return GenerationSettings(max_output_tokens=tokens, temperature=temperature)
