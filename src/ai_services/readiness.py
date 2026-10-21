"""Dependency registry and TCP reachability checks for readiness."""

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Literal

from ai_services.config import Dependency

CHECK_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class DependencyResult:
    name: str
    status: Literal["up", "down"]


async def check_dependency(
    dependency: Dependency, limit_seconds: float = CHECK_TIMEOUT_SECONDS
) -> bool:
    """True if a TCP connection to the dependency succeeds within the limit."""
    try:
        async with asyncio.timeout(limit_seconds):
            _, writer = await asyncio.open_connection(dependency.host, dependency.port)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def check_dependencies(dependencies: list[Dependency]) -> list[DependencyResult]:
    reachable = await asyncio.gather(*(check_dependency(d) for d in dependencies))
    return [
        DependencyResult(name=d.name, status="up" if ok else "down")
        for d, ok in zip(dependencies, reachable, strict=True)
    ]


def overall_status(results: list[DependencyResult]) -> Literal["ready", "not_ready"]:
    return "ready" if all(r.status == "up" for r in results) else "not_ready"
