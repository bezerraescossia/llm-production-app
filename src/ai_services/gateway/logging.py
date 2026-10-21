"""Content-free completion logs. These helpers take no message or answer text on purpose."""

from ai_services.logging import get_logger

log = get_logger("ai_services.gateway")


def log_completion_finished(
    *,
    tier: str,
    model: str,
    attempts: int,
    fallback_used: bool,
    first_output_ms: float,
    total_ms: float,
    finish_reason: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> None:
    log.info(
        "completion_finished",
        tier=tier,
        model=model,
        attempts=attempts,
        fallback_used=fallback_used,
        first_output_ms=round(first_output_ms, 1),
        total_ms=round(total_ms, 1),
        finish_reason=finish_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def log_attempt_failed(
    *, model: str, category: str, attempt: int | None = None, midstream: bool = False
) -> None:
    log.warning(
        "completion_attempt_failed",
        model=model,
        category=category,
        attempt=attempt,
        midstream=midstream,
    )
