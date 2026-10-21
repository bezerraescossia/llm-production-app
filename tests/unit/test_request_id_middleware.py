import re
import uuid

import httpx
from fastapi import FastAPI

from ai_services.context import current_request_id
from ai_services.middleware import RequestContextMiddleware


def build() -> httpx.AsyncClient:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(RequestContextMiddleware, contract_version="1.0.0")

    @app.get("/echo")
    async def echo() -> dict[str, str]:
        return {"request_id": current_request_id()}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_valid_client_request_id_is_reused() -> None:
    async with build() as c:
        r = await c.get("/echo", headers={"X-Request-Id": "client-id.0001"})
    assert r.headers["x-request-id"] == "client-id.0001"
    assert r.json()["request_id"] == "client-id.0001"


async def test_missing_or_invalid_request_id_is_replaced_by_uuid4() -> None:
    async with build() as c:
        missing = await c.get("/echo")
        for bad in ("short", "has spaces here", "x" * 200, "bad:colon-id"):
            r = await c.get("/echo", headers={"X-Request-Id": bad})
            assert r.headers["x-request-id"] != bad
            assert uuid.UUID(r.headers["x-request-id"]).version == 4
    assert uuid.UUID(missing.headers["x-request-id"]).version == 4


async def test_contract_version_header_on_every_response() -> None:
    async with build() as c:
        ok = await c.get("/echo")
        missing = await c.get("/nope")
    for r in (ok, missing):
        assert re.fullmatch(r"\d+\.\d+\.\d+", r.headers["x-contract-version"])
