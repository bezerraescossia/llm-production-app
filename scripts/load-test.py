"""Streaming load test: concurrent SSE streams against a running stack.

Usage: SERVICE_TOKEN=... uv run python scripts/load-test.py [--streams 20] [--base-url URL]

Passes only if every stream ends in exactly one `done` event and the 95th-percentile time to
first event is under --max-first-event-ms (default 500, SC-006).
"""

import argparse
import asyncio
import math
import os
import sys
import time

import httpx

BODY = {"messages": [{"role": "user", "content": "load test"}]}


async def one_stream(client: httpx.AsyncClient, token: str, n: int) -> tuple[float, list[str]]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": f"load-{n % 4}",
        "X-User-Id": f"user-{n}",
    }
    events: list[str] = []
    first: float | None = None
    start = time.perf_counter()
    async with client.stream("POST", "/v1/chat/stream", json=BODY, headers=headers) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                if first is None:
                    first = time.perf_counter() - start
                events.append(line.split(":", 1)[1].strip())
    if first is None:
        raise RuntimeError("stream produced no events")
    return first * 1000, events


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--streams", type=int, default=20)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8080"))
    parser.add_argument("--max-first-event-ms", type=float, default=500.0)
    args = parser.parse_args()
    token = os.environ.get("SERVICE_TOKEN")
    if not token:
        print("SERVICE_TOKEN must be set", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        results = await asyncio.gather(
            *(one_stream(client, token, n) for n in range(args.streams)), return_exceptions=True
        )

    failures: list[str] = []
    latencies: list[float] = []
    for n, result in enumerate(results):
        if isinstance(result, BaseException):
            failures.append(f"stream {n}: {type(result).__name__}: {result}")
            continue
        first_ms, events = result
        latencies.append(first_ms)
        if events.count("done") != 1 or events[-1] != "done":
            failures.append(f"stream {n}: events did not end in exactly one done: {events[-3:]}")

    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
        print(
            f"{len(latencies)}/{args.streams} streams completed; "
            f"first event p50={ordered[len(ordered) // 2]:.1f} ms p95={p95:.1f} ms "
            f"max={ordered[-1]:.1f} ms"
        )
        if p95 >= args.max_first_event_ms:
            failures.append(f"p95 {p95:.1f} ms >= {args.max_first_event_ms} ms")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
