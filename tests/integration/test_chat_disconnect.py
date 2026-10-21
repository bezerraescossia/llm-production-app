import asyncio

import httpx

from ai_services.config import Settings
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, run_server


async def test_client_disconnect_stops_the_stream_and_releases_resources() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        placeholder_token_delay_ms=200,
    )
    app = create_app(settings)
    async with run_server(app) as (base, _server):  # type: tuple[str, uvicorn.Server]
        async with httpx.AsyncClient(base_url=base, timeout=5) as c:
            async with c.stream("POST", "/v1/chat/stream", json=VALID_BODY, headers=auth()) as r:
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        break
                assert app.state.active_streams == 1
            # leaving the context closed the connection mid-stream
        for _ in range(100):
            if app.state.active_streams == 0:
                break
            await asyncio.sleep(0.02)
        assert app.state.active_streams == 0
