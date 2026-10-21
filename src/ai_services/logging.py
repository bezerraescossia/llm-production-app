"""Structured JSON logging with request context binding and secret redaction."""

import logging
import re
import sys
from typing import Any, TextIO, cast

import structlog
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

from ai_services.context import get_context

REDACTED = "[REDACTED]"
_SENSITIVE_WORDS = {"authorization", "token", "secret", "password", "credential", "credentials"}


def _is_sensitive(key: str) -> bool:
    return any(word in _SENSITIVE_WORDS for word in re.split(r"[^a-z0-9]+", key.lower()))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def add_request_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    ctx = get_context()
    if ctx is not None:
        event_dict.setdefault("request_id", ctx.request_id)
        if ctx.tenant_id is not None:
            event_dict.setdefault("tenant_id", ctx.tenant_id)
        if ctx.user_id is not None:
            event_dict.setdefault("user_id", ctx.user_id)
    return event_dict


def redact_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    result: EventDict = _redact(event_dict)
    return result


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_request_context,
            structlog.processors.format_exc_info,
            redact_secrets,
            structlog.processors.JSONRenderer(default=str),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.WriteLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger(name))
