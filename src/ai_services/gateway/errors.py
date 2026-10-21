"""Errors raised inside the gateway and their mapping to the service's documented error codes."""

from collections.abc import Sequence
from enum import StrEnum

from ai_services.errors import ErrorCode, ServiceError


class ProviderCategory(StrEnum):
    TEMPORARY = "temporary"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    AUTH = "auth"
    CONTEXT_TOO_LARGE = "context_too_large"
    CONTENT_BLOCKED = "content_blocked"
    INVALID_REQUEST = "invalid_request"


class ProviderError(Exception):
    """A classified provider failure. Carries the category only, never provider text."""

    def __init__(
        self, category: ProviderCategory, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(category.value)
        self.category = category
        self.retry_after_seconds = retry_after_seconds


_UPSTREAM_CODES = {
    ErrorCode.UPSTREAM_UNAVAILABLE: "No model is available to answer right now; retry shortly.",
    ErrorCode.UPSTREAM_TIMEOUT: "The model did not answer in time.",
    ErrorCode.UPSTREAM_ERROR: "The model provider could not process the request.",
    ErrorCode.INPUT_TOO_LARGE: "The conversation is too large for the requested tier.",
}
_RETRY_AFTER_SECONDS = 5


class GatewayError(ServiceError):
    """A completion failed before any output; surfaces as a standard HTTP error."""

    def __init__(self, code: ErrorCode, *, retry_after_seconds: int | None = None) -> None:
        if code not in _UPSTREAM_CODES:
            raise ValueError(f"{code.value} is not a gateway error code")
        super().__init__(code, _UPSTREAM_CODES[code], retry_after_seconds=retry_after_seconds)


def error_for_failures(seen: Sequence[ProviderCategory]) -> GatewayError:
    """Pick the final error from the categories of every failed attempt (research R6)."""
    if not seen:
        raise ValueError("no failures to summarise")
    categories = set(seen)
    P = ProviderCategory
    if categories <= {P.TIMEOUT}:
        return GatewayError(ErrorCode.UPSTREAM_TIMEOUT)
    if categories <= {P.AUTH, P.INVALID_REQUEST}:
        return GatewayError(ErrorCode.UPSTREAM_ERROR)
    if categories <= {P.CONTEXT_TOO_LARGE}:
        return GatewayError(ErrorCode.INPUT_TOO_LARGE)
    return GatewayError(ErrorCode.UPSTREAM_UNAVAILABLE, retry_after_seconds=_RETRY_AFTER_SECONDS)


class UnknownTierError(Exception):
    """A caller asked for a tier that is not configured (a programming or configuration error)."""

    def __init__(self, tier: str) -> None:
        super().__init__(f"unknown tier {tier!r}")
        self.tier = tier


class GenerationSettingError(Exception):
    """A caller tried to raise a generation setting above its tier ceiling."""

    def __init__(self, setting: str, *, requested: float, ceiling: float) -> None:
        super().__init__(f"{setting}={requested} exceeds the tier ceiling of {ceiling}")
        self.setting = setting
        self.requested = requested
        self.ceiling = ceiling
