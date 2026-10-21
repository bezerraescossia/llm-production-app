"""Per-request context carried in a context variable (request id, tenant, user)."""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RequestContext:
    request_id: str
    contract_version: str
    tenant_id: str | None = None
    user_id: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def set_context(ctx: RequestContext | None) -> Token[RequestContext | None]:
    return _current.set(ctx)


def reset_context(token: Token[RequestContext | None]) -> None:
    _current.reset(token)


def get_context() -> RequestContext | None:
    return _current.get()


def bind_identity(tenant_id: str, user_id: str) -> None:
    ctx = _current.get()
    if ctx is not None:
        ctx.tenant_id = tenant_id
        ctx.user_id = user_id


def current_request_id() -> str:
    ctx = _current.get()
    return ctx.request_id if ctx is not None else "unknown"
