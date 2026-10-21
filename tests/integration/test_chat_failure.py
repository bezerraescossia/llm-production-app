import httpx
from fastapi import FastAPI

from tests.conftest import VALID_BODY, auth, parse_sse


async def test_mid_stream_failure_ends_with_error_event(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.fail_after_events = 2
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    assert r.status_code == 200
    frames = parse_sse(r.text)
    kinds = [f["event"] for f in frames]
    assert kinds == ["token", "token", "error"]
    assert '"code":"internal_error"' in frames[-1]["data"]
    assert "done" not in kinds
    assert [int(f["id"]) for f in frames] == [0, 1, 2]
