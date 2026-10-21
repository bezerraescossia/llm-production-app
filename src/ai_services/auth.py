"""Service-credential check and tenant/user identity validation for protected routes."""

import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from ai_services.context import bind_identity
from ai_services.errors import ErrorCode, ServiceError, error_response
from ai_services.schemas import IDENTIFIER_PATTERN

PROTECTED_PATHS = frozenset({"/v1/chat/stream"})
TENANT_HEADER = "X-Tenant-Id"
USER_HEADER = "X-User-Id"
_BEARER = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    user_id: str


def extract_bearer(value: str | None) -> str | None:
    if not value:
        return None
    match = _BEARER.match(value.strip())
    return match.group(1) if match else None


def token_is_valid(candidate: str | None, tokens: list[str]) -> bool:
    """Compare against every configured token in constant time, with no early exit."""
    if not candidate:
        return False
    encoded = candidate.encode()
    valid = False
    for token in tokens:
        matched = hmac.compare_digest(encoded, token.encode())
        valid = valid or matched
    return valid


def _identifier(headers: Mapping[str, str], header: str) -> str:
    value = headers.get(header.lower())
    if value is None or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ServiceError(
            ErrorCode.INVALID_IDENTITY,
            f"{header} is missing or invalid.",
            details={"field": header},
        )
    return value


def validate_identity(headers: Mapping[str, str]) -> Identity:
    return Identity(
        tenant_id=_identifier(headers, TENANT_HEADER),
        user_id=_identifier(headers, USER_HEADER),
    )


class ServiceAuthMiddleware:
    """Runs before any body is read: credential first, then identity headers.

    This is a middleware rather than a route dependency because FastAPI reads the request body
    before it resolves dependencies, and the spec requires authentication to come first.
    """

    def __init__(self, app: ASGIApp, tokens: list[str]) -> None:
        self.app = app
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in PROTECTED_PATHS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        try:
            if not token_is_valid(extract_bearer(headers.get("authorization")), self.tokens):
                raise ServiceError(ErrorCode.UNAUTHORIZED, "Missing or invalid service credential.")
            identity = validate_identity(headers)
        except ServiceError as err:
            await error_response(err)(scope, receive, send)
            return
        bind_identity(identity.tenant_id, identity.user_id)
        await self.app(scope, receive, send)
