"""Generation settings: per-tier defaults and hard ceilings."""

from ai_services.gateway.config import GenerationLimits
from ai_services.gateway.errors import GenerationSettingError
from ai_services.gateway.types import GenerationSettings


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
