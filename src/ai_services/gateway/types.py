"""Plain types shared by the gateway, its providers and its callers."""

from dataclasses import dataclass, field
from typing import Literal

from ai_services.schemas import Message

FinishReason = Literal["stop", "length", "blocked"]


@dataclass(frozen=True)
class GenerationSettings:
    """Per-request generation settings. None means the tier default; callers may only lower them."""

    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class CompletionRequest:
    tier: str
    messages: list[Message]
    settings: GenerationSettings = field(default_factory=GenerationSettings)


@dataclass(frozen=True)
class Completion:
    """The collected form of a finished stream (returned by the full-answer helper)."""

    text: str
    finish_reason: FinishReason
    input_tokens: int | None
    output_tokens: int | None
    model: str
    attempts: int
    fallback_used: bool
