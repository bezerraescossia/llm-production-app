"""Per-model failure cool-down (in memory, per process; holds no tenant or message data)."""

import time
from collections.abc import Callable, Sequence

from ai_services.gateway.config import CooldownPolicy
from ai_services.gateway.errors import ProviderCategory

_COUNTED = {
    ProviderCategory.TEMPORARY,
    ProviderCategory.RATE_LIMITED,
    ProviderCategory.TIMEOUT,
    ProviderCategory.UNAVAILABLE,
    ProviderCategory.AUTH,
}


def counts_toward_cooldown(category: ProviderCategory) -> bool:
    """Only failures that say something about a model's health count; a safety block, a bad
    request or an oversized conversation say nothing about it."""
    return category in _COUNTED


class FailureCooldown:
    def __init__(self, policy: CooldownPolicy, clock: Callable[[], float] = time.monotonic) -> None:
        self._policy = policy
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}

    def record_failure(self, model: str) -> None:
        self._failures[model] = self._failures.get(model, 0) + 1
        if self._failures[model] >= self._policy.failure_threshold:
            self._skip_until[model] = self._clock() + self._policy.seconds

    def record_success(self, model: str) -> None:
        self._failures.pop(model, None)
        self._skip_until.pop(model, None)

    def is_cooling(self, model: str) -> bool:
        return self._clock() < self._skip_until.get(model, 0.0)

    def soonest(self, models: Sequence[str]) -> str:
        """The model whose cool-down ends first (used when every model is cooling down)."""
        return min(models, key=lambda m: self._skip_until.get(m, 0.0))

    def tracked_models(self) -> list[str]:
        return list(self._failures)
