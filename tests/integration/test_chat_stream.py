import time

import httpx
import uvicorn

from tests.conftest import VALID_BODY, auth, parse_sse


async def test_success_path_event_order_and_ids(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = parse_sse(r.text)
    kinds = [f["event"] for f in frames]
    assert kinds[-1] == "done" and kinds.count("done") == 1
    assert kinds[-2] == "usage"
    assert set(kinds[:-2]) == {"token"} and len(kinds) > 3
    assert [int(f["id"]) for f in frames] == list(range(len(frames)))
    assert '"finish_reason":"stop"' in frames[-1]["data"]
    assert r.headers["x-request-id"] and r.headers["x-contract-version"]


async def test_placeholder_is_deterministic(client: httpx.AsyncClient) -> None:
    first = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    second = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    assert first.text == second.text


async def test_first_event_arrives_within_500ms(live: tuple[str, uvicorn.Server]) -> None:
    base, _ = live
    async with httpx.AsyncClient(base_url=base, timeout=5) as c:
        start = time.perf_counter()
        async with c.stream("POST", "/v1/chat/stream", json=VALID_BODY, headers=auth()) as r:
            assert r.status_code == 200
            async for line in r.aiter_lines():
                if line.startswith("event:"):
                    break
            elapsed = time.perf_counter() - start
    assert elapsed < 0.5
