import io
import json
from typing import Any

import httpx
from fastapi import FastAPI

from ai_services.logging import configure_logging
from tests.conftest import TENANT_HEADERS, VALID_BODY, auth


def entries_for(buf: io.StringIO, request_id: str) -> list[dict[str, Any]]:
    parsed = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return [e for e in parsed if e.get("request_id") == request_id]


async def test_every_request_is_findable_by_its_id_with_identity(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)

    ok = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    app.state.fail_after_events = 1
    failed = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    app.state.fail_after_events = None
    rejected = await client.post("/v1/chat/stream", json=VALID_BODY, headers=TENANT_HEADERS)
    bad_identity = await client.post(
        "/v1/chat/stream", json=VALID_BODY, headers={"Authorization": auth()["Authorization"]}
    )

    for response in (ok, failed):
        found = entries_for(buf, response.headers["x-request-id"])
        assert len(found) >= 2  # at least the stream entries and the request summary
        assert all(e["tenant_id"] == "acme" and e["user_id"] == "u-1" for e in found)
    for response in (rejected, bad_identity):
        found = entries_for(buf, response.headers["x-request-id"])
        assert found, "rejected requests must be logged too"
    finish = [e for e in entries_for(buf, rejected.headers["x-request-id"]) if "status" in e]
    assert finish and finish[-1]["status"] == 401


async def test_request_summary_has_method_path_status_and_duration(
    client: httpx.AsyncClient,
) -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    summary = [
        e for e in entries_for(buf, r.headers["x-request-id"]) if e["event"] == "request_finished"
    ]
    assert len(summary) == 1
    assert summary[0]["method"] == "POST" and summary[0]["path"] == "/v1/chat/stream"
    assert summary[0]["status"] == 200 and summary[0]["duration_ms"] >= 0


async def test_client_supplied_request_id_appears_in_logs(client: httpx.AsyncClient) -> None:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    await client.post(
        "/v1/chat/stream", json=VALID_BODY, headers=auth(**{"X-Request-Id": "trace-me-0001"})
    )
    assert entries_for(buf, "trace-me-0001")
