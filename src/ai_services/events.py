"""Typed SSE events and an encoder that enforces ordering and a single terminal event."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenData(_Payload):
    index: int = Field(ge=0)
    text: str


class ToolCallData(_Payload):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResultData(_Payload):
    id: str
    name: str
    status: Literal["ok", "error"]
    content: str | None = None


class CitationData(_Payload):
    source_id: str
    title: str
    uri: str | None = None
    snippet: str | None = None


class UsageData(_Payload):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(ge=0)


class DoneData(_Payload):
    finish_reason: Literal["stop", "length", "blocked", "cancelled"]


class ErrorData(_Payload):
    code: str
    message: str


EVENT_MODELS: dict[str, type[_Payload]] = {
    "token": TokenData,
    "tool_call": ToolCallData,
    "tool_result": ToolResultData,
    "citation": CitationData,
    "usage": UsageData,
    "done": DoneData,
    "error": ErrorData,
}
TERMINAL_EVENTS = frozenset({"done", "error"})


class StreamClosedError(Exception):
    """Raised when an event is emitted after the terminal event."""


@dataclass(frozen=True)
class Frame:
    id: int
    event: str
    data: str

    def render(self) -> str:
        return f"id: {self.id}\nevent: {self.event}\ndata: {self.data}\n\n"


class EventSequencer:
    """Numbers events from 0 without gaps and refuses anything after done or error."""

    def __init__(self) -> None:
        self._next_id = 0
        self.closed = False

    def next(self, event: str, payload: dict[str, Any]) -> Frame:
        if self.closed:
            raise StreamClosedError("no events may follow a terminal event")
        model = EVENT_MODELS.get(event)
        if model is None:
            raise ValueError(f"unknown event type {event!r}")
        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"invalid {event} payload: {exc.error_count()} error(s)") from exc
        data = json.dumps(
            validated.model_dump(mode="json", exclude_unset=True), separators=(",", ":")
        )
        frame = Frame(id=self._next_id, event=event, data=data)
        self._next_id += 1
        if event in TERMINAL_EVENTS:
            self.closed = True
        return frame
