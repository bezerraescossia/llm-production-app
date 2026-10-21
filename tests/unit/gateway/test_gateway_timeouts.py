"""The four limits of FR-014, at millisecond scale, with real sleeping (no fake clock)."""

import time

import pytest

from ai_services.errors import ErrorCode
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig, RetryPolicy, Timeouts
from ai_services.gateway.errors import GatewayError
from ai_services.gateway.types import CompletionRequest
from tests.unit.gateway.helpers import USER_MESSAGES, RecordingStub, max_jitter


def build(
    models: list[str],
    *,
    first: float = 0.05,
    pre: float = 0.15,
    idle: float = 0.05,
    total: float = 0.3,
    retry: RetryPolicy | None = None,
    uniform=None,  # type: ignore[no-untyped-def]
) -> tuple[Gateway, RecordingStub]:
    stub = RecordingStub()
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": models, "large": ["stub/default"]}
    )
    cfg.timeouts = Timeouts(
        first_output_seconds=first, pre_output_seconds=pre, idle_seconds=idle, total_seconds=total
    )
    cfg.retry = retry or RetryPolicy(
        max_attempts_per_model=2, backoff_base_seconds=0.001, backoff_max_seconds=0.002
    )
    kwargs = {"uniform": uniform} if uniform else {}
    return Gateway(cfg, {"stub": stub}, **kwargs), stub


def request() -> CompletionRequest:
    return CompletionRequest("medium", USER_MESSAGES)


async def test_a_first_output_timeout_counts_as_a_timeout_attempt_and_falls_back() -> None:
    gateway, stub = build(["stub/stall", "stub/default"], pre=1.0, total=2.0)
    result = await gateway.complete(request())
    assert stub.calls == ["stall", "stall", "default"]  # retried once, then the next model
    assert result.fallback_used and stub.active == 0  # every stalled stream was closed


async def test_an_idle_stall_after_partial_output_ends_with_an_error_event_and_no_fallback() -> (
    None
):
    gateway, stub = build(["stub/stall-midstream", "stub/default"])
    started = time.perf_counter()
    out = [e async for e in gateway.stream(request())]
    assert [k for k, _ in out] == ["token", "error"]
    assert out[-1][1]["code"] == "upstream_timeout"
    assert stub.calls == ["stall-midstream"] and stub.active == 0
    assert time.perf_counter() - started < 0.4


async def test_the_total_limit_ends_a_slow_answer_and_closes_the_provider() -> None:
    gateway, stub = build(["stub/slow"], idle=0.05, total=0.1, pre=0.1, first=0.05)
    started = time.perf_counter()
    out = [e async for e in gateway.stream(request())]
    assert out[-1][0] == "error" and out[-1][1]["code"] == "upstream_timeout"
    assert [k for k, _ in out].count("token") >= 1
    assert time.perf_counter() - started < 0.3 and stub.active == 0


async def test_the_overall_wait_bounds_all_attempts_retries_and_fallbacks() -> None:
    # Six attempts of 0.05 s would take 0.3 s; the overall wait stops it at about 0.12 s.
    gateway, stub = build(["stub/stall", "stub/stall", "stub/stall"], pre=0.12, total=0.5)
    started = time.perf_counter()
    with pytest.raises(GatewayError) as exc:
        await gateway.open(request())
    elapsed = time.perf_counter() - started
    assert exc.value.code is ErrorCode.UPSTREAM_TIMEOUT and exc.value.status_code == 504
    assert 0.1 <= elapsed < 0.25
    assert len(stub.calls) < 6 and stub.active == 0


async def test_backoff_sleeps_never_exceed_the_remaining_overall_wait() -> None:
    retry = RetryPolicy(max_attempts_per_model=3, backoff_base_seconds=5, backoff_max_seconds=5)
    gateway, stub = build(
        ["stub/fail-temporary"], pre=0.2, total=0.5, retry=retry, uniform=max_jitter
    )
    started = time.perf_counter()
    with pytest.raises(GatewayError) as exc:
        await gateway.open(request())
    assert time.perf_counter() - started < 0.5  # not the 5 s the backoff alone would take
    assert exc.value.code is ErrorCode.UPSTREAM_TIMEOUT
    assert stub.calls == ["fail-temporary"]


async def test_the_limits_come_from_the_configuration() -> None:
    gateway, _ = build(["stub/stall"], first=0.03, pre=0.04, idle=0.03, total=0.05)
    assert gateway.config.timeouts.first_output_seconds == 0.03
    started = time.perf_counter()
    with pytest.raises(GatewayError):
        await gateway.open(request())
    assert time.perf_counter() - started < 0.15
