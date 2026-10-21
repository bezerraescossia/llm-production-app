import pytest

from ai_services.errors import ErrorCode
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig, ModelCandidate
from ai_services.gateway.errors import GatewayError
from ai_services.gateway.limits import estimate_tokens
from ai_services.gateway.types import CompletionRequest
from ai_services.schemas import Message
from tests.unit.gateway.helpers import RecordingStub


def messages(*sizes: int) -> list[Message]:
    return [Message(role="user", content="x" * n) for n in sizes]


def test_the_estimate_is_total_characters_over_three_rounded_up() -> None:
    assert estimate_tokens(messages(3)) == 1
    assert estimate_tokens(messages(4)) == 2
    assert estimate_tokens(messages(300, 301)) == 201
    assert estimate_tokens([]) == 0


def config(*limits: int) -> GatewayConfig:
    cfg = GatewayConfig.from_models({t: ["stub/default"] for t in ("small", "medium", "large")})
    cfg.tiers["medium"].models = [
        ModelCandidate(provider="stub", model_id="default", max_input_tokens=n) for n in limits
    ]
    return cfg


async def test_a_model_that_cannot_take_the_conversation_is_skipped() -> None:
    stub = RecordingStub()
    cfg = config(5, 1000)
    cfg.tiers["medium"].models[0] = ModelCandidate(
        provider="stub", model_id="slow", max_input_tokens=5
    )
    gateway = Gateway(cfg, {"stub": stub})
    result = await gateway.complete(CompletionRequest("medium", messages(300)))
    assert stub.calls == ["default"]  # the 5-token model was never called
    assert result.model == "stub/default" and result.fallback_used is True


async def test_when_no_model_can_take_it_the_error_comes_before_any_provider_call() -> None:
    stub = RecordingStub()
    gateway = Gateway(config(5, 10), {"stub": stub})
    with pytest.raises(GatewayError) as exc:
        await gateway.open(CompletionRequest("medium", messages(300)))
    assert exc.value.code is ErrorCode.INPUT_TOO_LARGE and exc.value.status_code == 422
    assert stub.calls == []


async def test_the_messages_are_never_truncated_or_altered() -> None:
    seen: list[list[Message]] = []

    class Spy(RecordingStub):
        async def stream(self, model_id, messages, settings, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
            seen.append(messages)
            async for chunk in super().stream(model_id, messages, settings):
                yield chunk

    original = messages(30, 60)
    gateway = Gateway(config(1000), {"stub": Spy()})
    await gateway.complete(CompletionRequest("medium", original))
    assert seen[0] == original and seen[0] is original
