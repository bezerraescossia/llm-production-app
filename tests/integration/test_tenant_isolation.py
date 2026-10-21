import asyncio
import io
import json

import httpx
from fastapi import FastAPI

from ai_services.logging import configure_logging
from tests.conftest import TOKEN_A, VALID_BODY, parse_sse


def headers(tenant: str, user: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN_A}",
        "X-Tenant-Id": tenant,
        "X-User-Id": user,
    }


async def test_two_tenants_in_parallel_stay_separate(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    pairs = [(f"tenant-{i}", f"user-{i}") for i in range(6)]

    responses = await asyncio.gather(
        *[client.post("/v1/chat/stream", json=VALID_BODY, headers=headers(t, u)) for t, u in pairs]
    )
    expected: dict[str, tuple[str, str]] = {}
    for (tenant, user), r in zip(pairs, responses, strict=True):
        assert r.status_code == 200
        assert parse_sse(r.text)[-1]["event"] == "done"
        expected[r.headers["x-request-id"]] = (tenant, user)

    entries = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    seen = {e["request_id"] for e in entries if e.get("request_id") in expected}
    assert seen == set(expected)  # every request logged something
    for entry in entries:
        rid = entry.get("request_id")
        if rid in expected:
            assert (entry["tenant_id"], entry["user_id"]) == expected[rid]
