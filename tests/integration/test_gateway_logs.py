"""One content-free summary per completion and one entry per failed attempt (FR-018)."""

import io
import json
from typing import Any

import httpx
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.context import RequestContext, bind_identity, set_context
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig, RetryPolicy
from ai_services.gateway.providers.stub import StubProvider
from ai_services.gateway.types import CompletionRequest
from ai_services.logging import configure_logging
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth
from tests.unit.gateway.helpers import USER_MESSAGES

FAST = RetryPolicy(max_attempts_per_model=2, backoff_base_seconds=0.001, backoff_max_seconds=0.002)


def entries(buf: io.StringIO, event: str, request_id: str | None = None) -> list[dict[str, Any]]:
    parsed = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return [
        e
        for e in parsed
        if e["event"] == event and (request_id is None or e.get("request_id") == request_id)
    ]


def config(medium: list[str]) -> GatewayConfig:
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": medium, "large": ["stub/default"]}
    )
    cfg.retry = FAST
    return cfg


async def post(cfg: GatewayConfig, buf: io.StringIO) -> httpx.Response:
    settings = Settings(_env_file=None, service_tokens=[TOKEN_A])  # type: ignore[call-arg]
    app = create_app(settings, gateway_config=cfg)
    configure_logging("INFO", stream=buf)  # create_app configured stdout; capture instead
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())


async def test_a_completion_that_needed_a_fallback_is_summarised_and_its_failures_listed() -> None:
    buf = io.StringIO()
    r = await post(config(["stub/fail-temporary", "stub/default"]), buf)
    rid = r.headers["x-request-id"]

    [summary] = entries(buf, "completion_finished", rid)
    assert summary["tier"] == "medium" and summary["model"] == "stub/default"
    assert summary["attempts"] == 3 and summary["fallback_used"] is True
    assert summary["finish_reason"] == "stop"
    assert summary["input_tokens"] == 0 and summary["output_tokens"] == 0
    assert summary["first_output_ms"] >= 0 and summary["total_ms"] >= summary["first_output_ms"]
    assert summary["tenant_id"] == "acme" and summary["user_id"] == "u-1"

    failed = entries(buf, "completion_attempt_failed", rid)
    assert len(failed) == 2
    for entry in failed:
        assert entry["model"] == "stub/fail-temporary" and entry["category"] == "temporary"
        assert entry["tenant_id"] == "acme" and entry["user_id"] == "u-1"


async def test_the_finish_reason_records_how_each_completion_ended() -> None:
    blocked, midstream = io.StringIO(), io.StringIO()
    r1 = await post(config(["stub/blocked"]), blocked)
    r2 = await post(config(["stub/fail-midstream"]), midstream)
    [b] = entries(blocked, "completion_finished", r1.headers["x-request-id"])
    [m] = entries(midstream, "completion_finished", r2.headers["x-request-id"])
    assert b["finish_reason"] == "blocked"
    assert m["finish_reason"] == "error"
    assert len(entries(midstream, "completion_attempt_failed", r2.headers["x-request-id"])) == 1


async def test_a_stream_closed_early_is_logged_as_cancelled() -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    gateway = Gateway(GatewayConfig.default(), {"stub": StubProvider()})
    stream = await gateway.open(CompletionRequest("medium", USER_MESSAGES))
    await stream.aclose()
    [summary] = entries(buf, "completion_finished")
    assert summary["finish_reason"] == "cancelled"


async def test_the_complete_helper_logs_like_a_stream_and_carries_the_request_context() -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    set_context(RequestContext(request_id="req-helper-0001", contract_version="1.1.0"))
    bind_identity("acme", "u-9")
    gateway = Gateway(GatewayConfig.default(), {"stub": StubProvider()})
    await gateway.complete(CompletionRequest("medium", USER_MESSAGES))
    [summary] = entries(buf, "completion_finished", "req-helper-0001")
    assert summary["tenant_id"] == "acme" and summary["user_id"] == "u-9"
    assert summary["model"] == "stub/default" and summary["finish_reason"] == "stop"
    set_context(None)


async def test_a_total_failure_logs_each_failed_attempt_and_no_summary() -> None:
    buf = io.StringIO()
    r = await post(config(["stub/fail-timeout"]), buf)
    rid = r.headers["x-request-id"]
    assert r.status_code == 504
    assert len(entries(buf, "completion_attempt_failed", rid)) == 2
    assert entries(buf, "completion_finished", rid) == []  # nothing was served
