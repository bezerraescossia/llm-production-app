"""Swagger UI is opt-in (ENABLE_DOCS) and documents the bearer-token scheme for Authorize."""

import httpx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from ai_services.config import Settings
from ai_services.main import create_app
from tests.conftest import TOKEN_A


async def test_docs_are_off_by_default(client: httpx.AsyncClient) -> None:
    for path in ("/v1/docs", "/v1/openapi.json"):
        r = await client.get(path)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


async def test_docs_served_when_enabled() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        enable_docs=True,
    )
    app = create_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            page = await c.get("/v1/docs")
            spec = await c.get("/v1/openapi.json")
    assert page.status_code == 200 and "swagger" in page.text.lower()
    assert "/v1/openapi.json" in page.text
    assert spec.status_code == 200 and "/v1/chat/stream" in spec.json()["paths"]


def test_bearer_scheme_is_documented_for_the_authorize_button(app: FastAPI) -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["serviceToken"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert schema["security"] == [{"serviceToken": []}]
    paths = schema["paths"]
    assert paths["/v1/health/live"]["get"]["security"] == []
    assert paths["/v1/contract"]["get"]["security"] == []
    assert paths["/v1/health/ready"]["get"]["security"] == [{}, {"serviceToken": []}]
    assert "security" not in paths["/v1/chat/stream"]["post"]  # inherits the global requirement
