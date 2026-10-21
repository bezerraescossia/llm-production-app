"""SC-007: no prompt text, answer text or credential appears in any gateway log entry."""

import io
from pathlib import Path

import httpx
import pytest
import yaml
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig, RetryPolicy
from ai_services.gateway.providers.stub import PLACEHOLDER_TEXT, StubProvider
from ai_services.gateway.types import CompletionRequest
from ai_services.logging import configure_logging
from ai_services.main import create_app
from ai_services.schemas import Message
from tests.conftest import TOKEN_A, auth

PROMPT = "SENTINEL-PROMPT-TEXT-7f3a9"
CREDENTIAL = "sk-ant-SENTINEL-CREDENTIAL-b81c"
BODY = {"messages": [{"role": "user", "content": PROMPT}]}
FAST = RetryPolicy(max_attempts_per_model=2, backoff_base_seconds=0.001, backoff_max_seconds=0.002)


def config(medium: list[str]) -> GatewayConfig:
    cfg = GatewayConfig.from_models(
        {"small": ["stub/default"], "medium": medium, "large": ["stub/default"]}
    )
    cfg.retry = FAST
    return cfg


async def run_scenarios(buf: io.StringIO) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
    )
    for models in (
        ["stub/default"],  # success
        ["stub/fail-temporary", "stub/default"],  # fallback
        ["stub/fail-temporary"],  # total failure (HTTP error)
        ["stub/fail-midstream"],  # failure after output
        ["stub/blocked"],  # safety block
        ["stub/fail-invalid"],  # rejected request
    ):
        app = create_app(settings, gateway_config=config(models))
        configure_logging("DEBUG", stream=buf)
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                await client.post("/v1/chat/stream", json=BODY, headers=auth())

    # cancellation: close a stream after the first piece
    configure_logging("DEBUG", stream=buf)
    gateway = Gateway(GatewayConfig.default(), {"stub": StubProvider()})
    stream = await gateway.open(CompletionRequest("medium", [Message(role="user", content=PROMPT)]))
    await stream.aclose()
    # the full-answer helper
    await gateway.complete(CompletionRequest("medium", [Message(role="user", content=PROMPT)]))


def invalid_startup(tmp_path: Path, buf: io.StringIO) -> str:
    path = tmp_path / "gateway.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tiers": {
                    "small": {"models": ["stub/default"]},
                    "medium": {"models": ["anthropic/claude-haiku-latest"]},
                    "large": {"models": ["stub/default"]},
                }
            }
        )
    )
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        gateway_config=path,
        anthropic_api_key=CREDENTIAL,
    )
    configure_logging("DEBUG", stream=buf)
    with pytest.raises(SystemExit) as exc:
        create_app(settings)
    return str(exc.value)


async def test_logs_contain_no_prompt_answer_or_credential(tmp_path: Path) -> None:
    buf = io.StringIO()
    await run_scenarios(buf)
    startup_error = invalid_startup(tmp_path, buf)
    logs = buf.getvalue()
    assert "completion_finished" in logs and "completion_attempt_failed" in logs
    for secret in (PROMPT, CREDENTIAL, "placeholder answer", PLACEHOLDER_TEXT, TOKEN_A):
        assert secret not in logs, f"{secret[:20]}... leaked into the logs"
    assert CREDENTIAL not in startup_error and PROMPT not in startup_error
