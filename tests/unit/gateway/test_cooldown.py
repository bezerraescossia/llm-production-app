import pytest

from ai_services.gateway.config import CooldownPolicy
from ai_services.gateway.cooldown import FailureCooldown, counts_toward_cooldown
from ai_services.gateway.errors import ProviderCategory
from tests.unit.gateway.helpers import FakeClock

POLICY = CooldownPolicy(failure_threshold=3, seconds=30)


def make() -> tuple[FailureCooldown, FakeClock]:
    clock = FakeClock()
    return FailureCooldown(POLICY, clock=clock), clock


def test_a_model_is_skipped_after_the_threshold_of_consecutive_failures() -> None:
    cooldown, _ = make()
    cooldown.record_failure("m")
    cooldown.record_failure("m")
    assert not cooldown.is_cooling("m")
    cooldown.record_failure("m")
    assert cooldown.is_cooling("m")


def test_the_cooldown_expires_after_the_configured_seconds() -> None:
    cooldown, clock = make()
    for _ in range(3):
        cooldown.record_failure("m")
    clock.advance(29.9)
    assert cooldown.is_cooling("m")
    clock.advance(0.2)
    assert not cooldown.is_cooling("m")  # the next request is a trial


def test_a_failed_trial_cools_the_model_again_immediately() -> None:
    cooldown, clock = make()
    for _ in range(3):
        cooldown.record_failure("m")
    clock.advance(31)
    assert not cooldown.is_cooling("m")
    cooldown.record_failure("m")
    assert cooldown.is_cooling("m")


def test_a_success_clears_the_failure_counter() -> None:
    cooldown, clock = make()
    for _ in range(3):
        cooldown.record_failure("m")
    clock.advance(31)
    cooldown.record_success("m")
    cooldown.record_failure("m")
    assert not cooldown.is_cooling("m")


def test_models_are_tracked_independently() -> None:
    cooldown, _ = make()
    for _ in range(3):
        cooldown.record_failure("a")
    assert cooldown.is_cooling("a") and not cooldown.is_cooling("b")


def test_the_soonest_to_recover_is_chosen_when_all_are_cooling() -> None:
    cooldown, clock = make()
    for _ in range(3):
        cooldown.record_failure("late")
    clock.advance(10)
    for _ in range(3):
        cooldown.record_failure("later")
    assert cooldown.soonest(["later", "late"]) == "late"


@pytest.mark.parametrize(
    ("category", "counts"),
    [
        (ProviderCategory.TEMPORARY, True),
        (ProviderCategory.RATE_LIMITED, True),
        (ProviderCategory.TIMEOUT, True),
        (ProviderCategory.UNAVAILABLE, True),
        (ProviderCategory.AUTH, True),
        (ProviderCategory.CONTENT_BLOCKED, False),
        (ProviderCategory.INVALID_REQUEST, False),
        (ProviderCategory.CONTEXT_TOO_LARGE, False),
    ],
)
def test_only_failures_that_say_something_about_model_health_count(
    category: ProviderCategory, counts: bool
) -> None:
    assert counts_toward_cooldown(category) is counts


def test_only_model_names_are_stored_never_tenant_or_message_data() -> None:
    cooldown, _ = make()
    cooldown.record_failure("anthropic/claude-haiku-5-5")
    assert set(cooldown.tracked_models()) == {"anthropic/claude-haiku-5-5"}
