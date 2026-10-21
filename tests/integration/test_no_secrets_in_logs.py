"""SC-008: no secret, credential header or request body appears anywhere in the logs."""

import io

import httpx
from fastapi import FastAPI

from ai_services.logging import configure_logging
from tests.conftest import TENANT_HEADERS, TOKEN_A, TOKEN_B

BODY_SECRET = "BODY-CONTENT-THAT-MUST-NEVER-BE-LOGGED"
WRONG_TOKEN = "wrong-token-" + "w" * 30


async def test_full_scenario_set_leaks_nothing(app: FastAPI, client: httpx.AsyncClient) -> None:
    buf = io.StringIO()
    configure_logging("DEBUG", stream=buf)
    body = {"messages": [{"role": "user", "content": BODY_SECRET}]}
    bearer_a = {"Authorization": f"Bearer {TOKEN_A}", **TENANT_HEADERS}

    await client.post("/v1/chat/stream", json=body, headers=bearer_a)  # success
    await client.post(
        "/v1/chat/stream", json=body, headers={"Authorization": f"Bearer {WRONG_TOKEN}"}
    )  # 401
    await client.post("/v1/chat/stream", json=body, headers={"Authorization": f"Bearer {TOKEN_B}"})
    await client.post(  # oversized
        "/v1/chat/stream", content=BODY_SECRET.encode() * 40000, headers=bearer_a
    )
    await client.post(  # validation error that includes the secret in the input
        "/v1/chat/stream",
        json={"messages": [{"role": "robot", "content": BODY_SECRET}]},
        headers=bearer_a,
    )
    app.state.fail_after_events = 1
    await client.post("/v1/chat/stream", json=body, headers=bearer_a)  # mid-stream failure
    await client.get("/v1/health/ready", headers=bearer_a)

    logs = buf.getvalue()
    assert logs.strip(), "expected some log output"
    for secret in (TOKEN_A, TOKEN_B, WRONG_TOKEN, BODY_SECRET, "Bearer "):
        assert secret not in logs, f"{secret[:12]}... leaked into logs"
