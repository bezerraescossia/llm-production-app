import pytest

from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig
from ai_services.gateway.errors import UnknownTierError
from ai_services.gateway.providers.base import ProviderChunk
from ai_services.gateway.providers.stub import PLACEHOLDER_TEXT, StubProvider
from ai_services.gateway.types import CompletionRequest
from tests.unit.gateway.helpers import USER_MESSAGES, ScriptedProvider


def request(tier: str = "medium") -> CompletionRequest:
    return CompletionRequest(tier=tier, messages=USER_MESSAGES)


def stub_gateway(**tiers: list[str]) -> Gateway:
    models = {"small": ["stub/default"], "medium": ["stub/default"], "large": ["stub/default"]}
    models.update(tiers)
    return Gateway(GatewayConfig.from_models(models), {"stub": StubProvider()})


async def events(gateway: Gateway, req: CompletionRequest) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    return [event async for event in gateway.stream(req)]


async def test_stream_yields_tokens_then_one_usage_then_one_done() -> None:
    out = await events(stub_gateway(), request())
    kinds = [kind for kind, _ in out]
    assert kinds[:-2] == ["token"] * (len(kinds) - 2) and kinds[-2:] == ["usage", "done"]
    assert [p["index"] for k, p in out if k == "token"] == list(range(len(kinds) - 2))
    assert "".join(p["text"] for k, p in out if k == "token") == PLACEHOLDER_TEXT
    assert out[-1][1] == {"finish_reason": "stop"}
    assert out[-2][1] == {"input_tokens": 0, "output_tokens": 0, "cost_usd": None}


@pytest.mark.parametrize(
    "script",
    [
        [
            ProviderChunk(text="a "),
            ProviderChunk(finish_reason="stop"),
            ProviderChunk(usage=(5, 2)),
        ],
        [
            ProviderChunk(text="a "),
            ProviderChunk(usage=(5, 2)),
            ProviderChunk(finish_reason="stop"),
        ],
    ],
)
async def test_usage_always_precedes_done_whatever_order_the_provider_uses(
    script: list[ProviderChunk],
) -> None:
    gateway = Gateway(
        GatewayConfig.from_models({t: ["fake/m"] for t in ("small", "medium", "large")}),
        {"fake": ScriptedProvider(script)},
    )
    out = await events(gateway, request())
    assert [k for k, _ in out] == ["token", "usage", "done"]
    assert out[1][1] == {"input_tokens": 5, "output_tokens": 2, "cost_usd": None}


async def test_missing_usage_is_reported_as_unknown_and_missing_finish_as_stop() -> None:
    script = [ProviderChunk(text="a ")]
    gateway = Gateway(
        GatewayConfig.from_models({t: ["fake/m"] for t in ("small", "medium", "large")}),
        {"fake": ScriptedProvider(script)},
    )
    out = await events(gateway, request())
    assert out[-2] == ("usage", {"input_tokens": None, "output_tokens": None, "cost_usd": None})
    assert out[-1] == ("done", {"finish_reason": "stop"})


async def test_unknown_tier_fails_before_any_provider_is_called() -> None:
    provider = ScriptedProvider([ProviderChunk(text="x")])
    gateway = Gateway(
        GatewayConfig.from_models({t: ["fake/m"] for t in ("small", "medium", "large")}),
        {"fake": provider},
    )
    with pytest.raises(UnknownTierError, match="huge"):
        await gateway.open(request("huge"))
    assert provider.calls == 0


async def test_empty_answer_still_yields_usage_and_done() -> None:
    out = await events(stub_gateway(medium=["stub/empty"]), request())
    assert [k for k, _ in out] == ["usage", "done"]


async def test_each_tier_uses_its_own_model() -> None:
    gateway = stub_gateway(small=["stub/empty"], large=["stub/blocked"])
    assert [k for k, _ in await events(gateway, request("small"))] == ["usage", "done"]
    large = await events(gateway, request("large"))
    assert large[-1] == ("done", {"finish_reason": "blocked"})
    medium = await events(gateway, request("medium"))
    assert len(medium) > 3


async def test_open_returns_the_first_event_and_closing_closes_the_provider() -> None:
    provider = ScriptedProvider([ProviderChunk(text="a "), ProviderChunk(text="b ")])
    gateway = Gateway(
        GatewayConfig.from_models({t: ["fake/m"] for t in ("small", "medium", "large")}),
        {"fake": provider},
    )
    stream = await gateway.open(request())
    assert stream.first == ("token", {"index": 0, "text": "a "})
    rest = [event async for event in stream]
    assert rest[0] == stream.first  # iteration starts with the first event
    stream2 = await gateway.open(request())
    await stream2.aclose()
    assert provider.closed == 2


async def test_complete_returns_the_collected_stream() -> None:
    gateway = stub_gateway()
    streamed = await events(gateway, request())
    text = "".join(p["text"] for k, p in streamed if k == "token")
    result = await gateway.complete(request())
    assert result.text == text == PLACEHOLDER_TEXT
    assert result.finish_reason == "stop"
    assert (result.input_tokens, result.output_tokens) == (0, 0)
    assert result.model == "stub/default" and result.attempts == 1 and result.fallback_used is False


async def test_complete_reports_a_blocked_answer() -> None:
    result = await stub_gateway(medium=["stub/blocked"]).complete(request())
    assert result.text == "" and result.finish_reason == "blocked"
