import json
from collections.abc import AsyncIterator

import httpx

from tests.conftest import TENANT_HEADERS, TOKEN_A, VALID_BODY, auth

URL = "/v1/chat/stream"


def assert_error(r: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert r.status_code == status, r.text
    assert "text/event-stream" not in r.headers.get("content-type", "")
    body = r.json()["error"]
    assert body["code"] == code
    assert body["request_id"] == r.headers["x-request-id"]
    return dict(body)


async def test_no_token_is_401(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, json=VALID_BODY, headers=TENANT_HEADERS)
    assert_error(r, 401, "unauthorized")


async def test_wrong_token_is_401(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, json=VALID_BODY, headers=auth("z" * 40))
    assert_error(r, 401, "unauthorized")


async def test_auth_runs_before_body_parsing(client: httpx.AsyncClient) -> None:
    # Bad token plus an oversized and malformed body: still 401, never 413 or 422.
    r = await client.post(
        URL, content=b"{" + b"x" * 300_000, headers={**TENANT_HEADERS, "Authorization": "Bearer no"}
    )
    assert_error(r, 401, "unauthorized")


async def test_missing_tenant_or_user_is_400_naming_field(client: httpx.AsyncClient) -> None:
    for header in ("X-Tenant-Id", "X-User-Id"):
        headers = auth()
        del headers[header]
        r = await client.post(URL, json=VALID_BODY, headers=headers)
        body = assert_error(r, 400, "invalid_identity")
        assert body["details"] == {"field": header}


async def test_invalid_json_and_schema_are_422(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, content=b"{not json", headers=auth())
    assert_error(r, 422, "validation_error")
    r = await client.post(URL, json={"messages": "nope"}, headers=auth())
    assert_error(r, 422, "validation_error")
    r = await client.post(URL, json={"messages": []}, headers=auth())
    assert_error(r, 422, "validation_error")


async def test_error_details_do_not_echo_user_content(client: httpx.AsyncClient) -> None:
    secret = "SUPER-SECRET-CONTENT"
    r = await client.post(
        URL, json={"messages": [{"role": "robot", "content": secret}]}, headers=auth()
    )
    assert r.status_code == 422 and secret not in r.text


async def test_last_message_assistant_is_422(client: httpx.AsyncClient) -> None:
    body = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    assert_error(await client.post(URL, json=body, headers=auth()), 422, "validation_error")


async def test_101_messages_is_history_too_long(client: httpx.AsyncClient) -> None:
    body = {"messages": [{"role": "user", "content": "x"}] * 101}
    assert_error(await client.post(URL, json=body, headers=auth()), 422, "history_too_long")


async def test_configured_lower_message_limit_applies(settings, app) -> None:  # type: ignore[no-untyped-def]
    settings.max_messages = 3
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = {"messages": [{"role": "user", "content": "x"}] * 3}
        assert (await c.post(URL, json=ok, headers=auth())).status_code == 200
        too_many = {"messages": [{"role": "user", "content": "x"}] * 4}
        assert_error(await c.post(URL, json=too_many, headers=auth()), 422, "history_too_long")


async def test_oversized_body_is_413_by_content_length(client: httpx.AsyncClient) -> None:
    body = json.dumps({"messages": [{"role": "user", "content": "x" * 300_000}]})
    assert_error(await client.post(URL, content=body, headers=auth()), 413, "payload_too_large")


async def test_oversized_chunked_body_is_413_without_buffering_it_all(
    client: httpx.AsyncClient,
) -> None:
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(200):  # 200 x 64 KiB = 12.5 MiB if fully consumed
            sent += 1
            yield b"x" * 65536

    r = await client.post(URL, content=chunks(), headers=auth())
    assert_error(r, 413, "payload_too_large")
    assert sent < 20  # the server stopped reading shortly after the 256 KiB limit


async def test_unknown_route_uses_error_shape(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/nope", headers={"Authorization": f"Bearer {TOKEN_A}"})
    assert_error(r, 404, "not_found")
    assert_error(await client.get(URL, headers=auth()), 405, "method_not_allowed")
