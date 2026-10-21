"""POST /v1/chat/stream: stream an answer as typed server-sent events."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette import EventSourceResponse, ServerSentEvent
from sse_starlette.sse import AppStatus

from ai_services.errors import ErrorCode, ServiceError
from ai_services.events import EventSequencer, Frame
from ai_services.gateway import CompletionStream
from ai_services.gateway.types import CompletionRequest
from ai_services.logging import get_logger
from ai_services.schemas import ChatRequest, Error

log = get_logger(__name__)
router = APIRouter(prefix="/v1")

# In-flight streams must drain within the grace period instead of being cut at SIGTERM.
AppStatus.disable_automatic_graceful_drain()  # type: ignore[no-untyped-call]


def _sse(frame: Frame) -> ServerSentEvent:
    return ServerSentEvent(data=frame.data, event=frame.event, id=str(frame.id))


async def _stream(
    request: Request, completion: CompletionStream, message_count: int
) -> AsyncIterator[ServerSentEvent]:
    state = request.app.state
    sequencer = EventSequencer()
    state.active_streams += 1
    log.info("chat_stream_started", messages=message_count)
    try:
        try:
            async for event, payload in completion:
                yield _sse(sequencer.next(event, payload))
        except Exception as exc:
            log.error("chat_stream_failed", error_type=type(exc).__name__)
            yield _sse(
                sequencer.next(
                    "error",
                    {"code": ErrorCode.INTERNAL_ERROR.value, "message": "The stream failed."},
                )
            )
        else:
            log.info("chat_stream_completed")
    finally:
        await completion.aclose()
        state.active_streams -= 1


_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Stream of typed events ending in exactly one done or error event.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    400: {"model": Error, "description": "Tenant or user identity missing or invalid."},
    401: {"model": Error, "description": "Missing or invalid service credential."},
    413: {"model": Error, "description": "Body exceeds the size limit."},
    422: {
        "model": Error,
        "description": "Validation failed, history over the limit, or input too large.",
    },
    429: {"model": Error, "description": "Reserved: rate limit exceeded."},
    500: {"model": Error, "description": "Unexpected failure before streaming started."},
    502: {
        "model": Error,
        "description": "The model provider rejected the request (upstream_error).",
    },
    503: {
        "model": Error,
        "description": "Service is draining, or every model of the tier is unavailable.",
    },
    504: {"model": Error, "description": "Every attempt timed out before any output."},
}


def _header(name: str, required: bool) -> dict[str, object]:
    return {"name": name, "in": "header", "required": required, "schema": {"type": "string"}}


@router.post(
    "/chat/stream",
    operation_id="chatStream",
    response_model=None,
    response_class=EventSourceResponse,
    responses=_ERROR_RESPONSES,
    openapi_extra={
        "parameters": [
            _header("X-Tenant-Id", True),
            _header("X-User-Id", True),
            _header("X-Request-Id", False),
        ]
    },
)
async def chat_stream(request: Request, body: ChatRequest) -> EventSourceResponse:
    state = request.app.state
    limit = state.settings.max_messages
    if len(body.messages) > limit:
        raise ServiceError(
            ErrorCode.HISTORY_TOO_LONG,
            f"The message history exceeds {limit} messages.",
        )
    gateway = state.gateway
    # Wait for the first output so a failure before it is a normal HTTP error (FR-024).
    completion = await gateway.open(CompletionRequest(gateway.default_tier, body.messages))
    return EventSourceResponse(_stream(request, completion, len(body.messages)))
