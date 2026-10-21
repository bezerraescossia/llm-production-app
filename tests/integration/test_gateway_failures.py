"""Failures through the chat route: HTTP errors before output, error events after it."""

import httpx
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.gateway.config import GatewayConfig, RetryPolicy
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, parse_sse

FAST = RetryPolicy(max_attempts_per_model=2, backoff_base_seconds=0.001, backoff_max_seconds=0.002)


def config(medium: list[str], **limits: int) -> GatewayConfig:
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": medium, "large": ["stub/default"]}
    )
    cfg.retry = FAST
    for model in cfg.tiers["medium"].models:
        if limits:
            model.max_input_tokens = limits["max_input_tokens"]
    return cfg


async def post(cfg: GatewayConfig, body: dict | None = None) -> httpx.Response:  # type: ignore[type-arg]
    settings = Settings(_env_file=None, service_tokens=[TOKEN_A])  # type: ignore[call-arg]
    app = create_app(settings, gateway_config=cfg)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.post("/v1/chat/stream", json=body or VALID_BODY, headers=auth())


def assert_http_error(r: httpx.Response, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    assert "text/event-stream" not in r.headers["content-type"]  # no stream was opened
    body = r.json()["error"]
    assert body["code"] == code and body["request_id"] == r.headers["x-request-id"]


async def test_a_failing_first_model_falls_back_and_the_answer_completes() -> None:
    r = await post(config(["stub/fail-temporary", "stub/default"]))
    kinds = [f["event"] for f in parse_sse(r.text)]
    assert r.status_code == 200 and kinds[-2:] == ["usage", "done"] and "error" not in kinds


async def test_every_model_unavailable_is_503_with_retry_after() -> None:
    r = await post(config(["stub/fail-temporary", "stub/fail-rate-limited"]))
    assert_http_error(r, 503, "upstream_unavailable")
    assert int(r.headers["retry-after"]) > 0


async def test_every_attempt_timing_out_is_504() -> None:
    assert_http_error(await post(config(["stub/fail-timeout"])), 504, "upstream_timeout")


async def test_a_provider_rejection_is_502() -> None:
    assert_http_error(await post(config(["stub/fail-auth"])), 502, "upstream_error")


async def test_input_too_large_for_the_tier_is_422() -> None:
    cfg = config(["stub/default"], max_input_tokens=5)
    body = {"messages": [{"role": "user", "content": "x" * 300}]}
    assert_http_error(await post(cfg, body), 422, "input_too_large")


async def test_a_failure_after_output_started_is_an_error_event_with_no_fallback() -> None:
    r = await post(config(["stub/fail-midstream", "stub/default"]))
    frames = parse_sse(r.text)
    assert r.status_code == 200
    assert [f["event"] for f in frames] == ["token", "token", "error"]
    assert '"code":"upstream_unavailable"' in frames[-1]["data"]


async def test_a_safety_block_finishes_blocked_and_the_second_model_is_not_used() -> None:
    r = await post(config(["stub/blocked", "stub/default"]))
    frames = parse_sse(r.text)
    assert [f["event"] for f in frames] == ["usage", "done"]
    assert '"finish_reason":"blocked"' in frames[-1]["data"]
