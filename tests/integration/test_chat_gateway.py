import httpx
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig
from ai_services.gateway.providers.stub import PLACEHOLDER_TEXT, StubProvider
from ai_services.gateway.types import CompletionRequest
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, parse_sse
from tests.unit.gateway.helpers import USER_MESSAGES


async def test_default_config_serves_the_deterministic_placeholder(
    client: httpx.AsyncClient, app
) -> None:  # type: ignore[no-untyped-def]
    assert isinstance(app.state.gateway, Gateway)
    assert app.state.gateway.default_tier == "medium"
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    frames = parse_sse(r.text)
    kinds = [f["event"] for f in frames]
    assert kinds[-2:] == ["usage", "done"] and set(kinds[:-2]) == {"token"}
    import json

    text = "".join(json.loads(f["data"])["text"] for f in frames if f["event"] == "token")
    assert text == PLACEHOLDER_TEXT


async def test_chat_route_uses_the_configured_default_tier() -> None:
    settings = Settings(_env_file=None, service_tokens=[TOKEN_A])  # type: ignore[call-arg]
    config = GatewayConfig.from_models(
        {"small": ["stub/empty"], "medium": ["stub/default"], "large": ["stub/blocked"]},
        default_tier="small",
    )
    app = create_app(settings, gateway_config=config)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    assert [f["event"] for f in parse_sse(r.text)] == ["usage", "done"]


async def test_all_tiers_return_identical_event_shapes() -> None:
    gateway = Gateway(
        GatewayConfig.from_models(
            {"small": ["stub/default"], "medium": ["stub/default"], "large": ["stub/default"]}
        ),
        {"stub": StubProvider()},
    )
    shapes = []
    for tier in ("small", "medium", "large"):
        events = [e async for e in gateway.stream(CompletionRequest(tier, USER_MESSAGES))]
        shapes.append([(kind, sorted(payload)) for kind, payload in events])
    assert shapes[0] == shapes[1] == shapes[2]
