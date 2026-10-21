import asyncio

import httpx

from ai_services.config import Settings
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, parse_sse, run_server


async def test_new_requests_refused_while_in_flight_stream_completes() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        placeholder_token_delay_ms=30,
        shutdown_grace_seconds=20,
    )
    app = create_app(settings)
    async with run_server(app) as (base, _server):
        async with httpx.AsyncClient(base_url=base, timeout=10) as c:

            async def in_flight() -> httpx.Response:
                return await c.post("/v1/chat/stream", json=VALID_BODY, headers=auth())

            running = asyncio.create_task(in_flight())
            for _ in range(100):
                if app.state.active_streams == 1:
                    break
                await asyncio.sleep(0.01)
            app.state.begin_shutdown()

            refused = await c.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
            assert refused.status_code == 503
            assert refused.json()["error"]["code"] == "shutting_down"
            assert int(refused.headers["retry-after"]) > 0

            finished = await asyncio.wait_for(running, timeout=settings.shutdown_grace_seconds)
            frames = parse_sse(finished.text)
            assert finished.status_code == 200 and frames[-1]["event"] == "done"
