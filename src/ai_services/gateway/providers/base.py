"""The provider interface: every provider yields the same normalised chunks."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from ai_services.gateway.types import FinishReason, GenerationSettings
from ai_services.schemas import Message


@dataclass(frozen=True)
class ProviderChunk:
    """Exactly one of text, finish_reason or usage is set.

    A well-behaved provider yields text pieces first, then one finish reason, then one usage
    (token counts are None when the provider did not report them).
    """

    text: str | None = None
    finish_reason: FinishReason | None = None
    usage: tuple[int | None, int | None] | None = None


class Provider(Protocol):
    def stream(
        self,
        model_id: str,
        messages: list[Message],
        settings: GenerationSettings,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncGenerator[ProviderChunk, None]:
        """Stream a completion. Raises ProviderError for classified provider failures."""
        ...
