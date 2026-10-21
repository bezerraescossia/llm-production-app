"""Retries, in-tier fallback, safety blocks, mid-stream failures and cool-down (FR-009 to 013)."""

import pytest

from ai_services.errors import ErrorCode
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig
from ai_services.gateway.errors import GatewayError, ProviderCategory
from ai_services.gateway.types import CompletionRequest
from tests.unit.gateway.helpers import (
    USER_MESSAGES,
    FakeClock,
    FakeSleep,
    RaisingProvider,
    RecordingStub,
    max_jitter,
)


def build(
    small: list[str] | None = None,
    medium: list[str] | None = None,
    *,
    providers: dict | None = None,  # type: ignore[type-arg]
) -> tuple[Gateway, RecordingStub, FakeSleep, FakeClock]:
    stub = RecordingStub()
    sleep, clock = FakeSleep(), FakeClock()
    config = GatewayConfig.from_models(
        {
            "small": small or ["stub/default"],
            "medium": medium or ["stub/default"],
            "large": ["stub/default"],
        }
    )
    gateway = Gateway(
        config, {"stub": stub, **(providers or {})}, sleep=sleep, uniform=max_jitter, clock=clock
    )
    return gateway, stub, sleep, clock


def request(tier: str = "medium") -> CompletionRequest:
    return CompletionRequest(tier, USER_MESSAGES)


async def events(gateway: Gateway, tier: str = "medium") -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    return [event async for event in gateway.stream(request(tier))]


async def test_temporary_failures_are_retried_with_backoff_then_the_next_model_is_used() -> None:
    gateway, stub, sleep, _ = build(medium=["stub/fail-temporary", "stub/default"])
    result = await gateway.complete(request())
    assert stub.calls == ["fail-temporary", "fail-temporary", "default"]
    assert sleep.sleeps == [0.25]  # one backoff between the two attempts, none before a fallback
    assert result.model == "stub/default" and result.attempts == 3 and result.fallback_used


async def test_timeouts_are_retried_like_temporary_failures() -> None:
    gateway, stub, sleep, _ = build(medium=["stub/fail-timeout", "stub/default"])
    await gateway.complete(request())
    assert stub.calls == ["fail-timeout", "fail-timeout", "default"] and len(sleep.sleeps) == 1


async def test_a_provider_retry_hint_is_honored_and_capped_at_five_seconds() -> None:
    hinted = RaisingProvider(ProviderCategory.RATE_LIMITED, retry_after_seconds=60)
    gateway, stub, sleep, _ = build(medium=["fake/m", "stub/default"], providers={"fake": hinted})
    await gateway.complete(request())
    assert hinted.calls == 2 and sleep.sleeps == [5.0]

    gateway2, _, sleep2, _ = build(medium=["stub/fail-rate-limited", "stub/default"])
    await gateway2.complete(request())
    assert sleep2.sleeps == [0.01]  # the stub's own small hint, below the cap


@pytest.mark.parametrize("model", ["fail-unavailable", "fail-auth", "fail-context"])
async def test_non_retryable_model_failures_fall_back_immediately(model: str) -> None:
    gateway, stub, sleep, _ = build(medium=[f"stub/{model}", "stub/default"])
    result = await gateway.complete(request())
    assert stub.calls == [model, "default"] and sleep.sleeps == []
    assert result.fallback_used


async def test_an_invalid_request_is_neither_retried_nor_replaced() -> None:
    gateway, stub, sleep, _ = build(medium=["stub/fail-invalid", "stub/default"])
    with pytest.raises(GatewayError) as exc:
        await gateway.open(request())
    assert exc.value.code is ErrorCode.UPSTREAM_ERROR
    assert stub.calls == ["fail-invalid"] and sleep.sleeps == []


async def test_a_safety_block_is_neither_retried_nor_replaced_and_ends_as_blocked() -> None:
    blocked = RaisingProvider(ProviderCategory.CONTENT_BLOCKED)
    gateway, stub, _, _ = build(medium=["fake/m", "stub/default"], providers={"fake": blocked})
    out = await events(gateway)
    assert [k for k, _ in out] == ["usage", "done"]
    assert out[-1] == ("done", {"finish_reason": "blocked"})
    assert blocked.calls == 1 and stub.calls == []


async def test_a_failure_after_the_first_piece_never_retries_or_falls_back() -> None:
    gateway, stub, sleep, _ = build(medium=["stub/fail-midstream", "stub/default"])
    out = await events(gateway)
    assert [k for k, _ in out] == ["token", "token", "error"]
    assert out[-1][1]["code"] == "upstream_unavailable" and out[-1][1]["message"]
    assert stub.calls == ["fail-midstream"] and sleep.sleeps == []


@pytest.mark.parametrize(
    ("models", "code"),
    [
        (["stub/fail-temporary", "stub/fail-rate-limited"], ErrorCode.UPSTREAM_UNAVAILABLE),
        (["stub/fail-timeout"], ErrorCode.UPSTREAM_TIMEOUT),
        (["stub/fail-auth"], ErrorCode.UPSTREAM_ERROR),
        (["stub/fail-temporary", "stub/fail-timeout"], ErrorCode.UPSTREAM_UNAVAILABLE),
        (["stub/fail-context", "stub/fail-context"], ErrorCode.INPUT_TOO_LARGE),
    ],
)
async def test_when_every_model_fails_the_error_follows_the_failure_categories(
    models: list[str], code: ErrorCode
) -> None:
    gateway, *_ = build(medium=models)
    with pytest.raises(GatewayError) as exc:
        await gateway.open(request())
    assert exc.value.code is code


async def test_unavailable_errors_carry_a_retry_hint() -> None:
    gateway, *_ = build(medium=["stub/fail-temporary"])
    with pytest.raises(GatewayError) as exc:
        await gateway.open(request())
    assert (exc.value.retry_after_seconds or 0) > 0


async def test_fallback_never_leaves_the_requested_tier() -> None:
    gateway, stub, _, _ = build(small=["stub/fail-temporary"], medium=["stub/default"])
    with pytest.raises(GatewayError):
        await gateway.open(request("small"))
    assert stub.calls == ["fail-temporary", "fail-temporary"]  # medium's model was never tried


async def test_complete_surfaces_the_same_errors_as_the_stream() -> None:
    gateway, *_ = build(medium=["stub/fail-temporary"])
    with pytest.raises(GatewayError) as exc:
        await gateway.complete(request())
    assert exc.value.code is ErrorCode.UPSTREAM_UNAVAILABLE

    midstream, *_ = build(medium=["stub/fail-midstream"])
    with pytest.raises(GatewayError) as exc2:
        await midstream.complete(request())
    assert exc2.value.code is ErrorCode.UPSTREAM_UNAVAILABLE


async def test_a_repeatedly_failing_model_is_skipped_then_tried_again_after_the_cooldown() -> None:
    gateway, stub, _, clock = build(medium=["stub/fail-temporary", "stub/default"])
    await gateway.complete(request())  # two failures on the first model
    assert stub.calls == ["fail-temporary", "fail-temporary", "default"]
    stub.calls.clear()
    await gateway.complete(request())  # the third failure trips the cool-down: no retry
    assert stub.calls == ["fail-temporary", "default"]
    stub.calls.clear()
    await gateway.complete(request())  # now skipped entirely
    assert stub.calls == ["default"]
    clock.advance(31)
    stub.calls.clear()
    await gateway.complete(request())  # trial after the cool-down
    assert stub.calls[0] == "fail-temporary"


async def test_when_every_model_is_cooling_down_the_soonest_to_recover_is_still_tried() -> None:
    gateway, stub, _, clock = build(medium=["stub/fail-temporary", "stub/fail-unavailable"])
    for _ in range(4):
        with pytest.raises(GatewayError):
            await gateway.open(request())
    stub.calls.clear()
    with pytest.raises(GatewayError):
        await gateway.open(request())
    assert len(stub.calls) >= 1  # it did not fail without trying
    clock.advance(31)
