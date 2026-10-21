"""Deterministic placeholder answer used until a model is wired in (spec 002)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

PLACEHOLDER_TEXT = "This is a placeholder answer from the AI-services foundation."


async def placeholder_events(
    delay_ms: int = 0, fail_after: int | None = None
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (event, payload) pairs: word tokens, then usage, then done.

    `fail_after` injects a fault after that many events; tests set it through
    `app.state.fail_after_events`.
    """
    words = PLACEHOLDER_TEXT.split(" ")
    emitted = 0
    for index, word in enumerate(words):
        if fail_after is not None and emitted >= fail_after:
            raise RuntimeError("injected fault")
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        text = word if index == len(words) - 1 else word + " "
        yield "token", {"index": index, "text": text}
        emitted += 1
    yield "usage", {"input_tokens": 0, "output_tokens": 0, "cost_usd": None}
    yield "done", {"finish_reason": "stop"}
