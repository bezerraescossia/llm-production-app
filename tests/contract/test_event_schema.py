"""Every emitted SSE frame validates against events.schema.json."""

import json
from typing import Any

import httpx
from fastapi import FastAPI
from jsonschema import Draft202012Validator

from tests.conftest import VALID_BODY, auth, parse_sse
from tests.contract.helpers import load_events_schema

SCHEMA = load_events_schema()
VALIDATOR = Draft202012Validator(SCHEMA)
EVENT_TYPES = {"token", "tool_call", "tool_result", "citation", "usage", "done", "error"}


def as_event(frame: dict[str, str]) -> dict[str, Any]:
    return {"event": frame["event"], "data": json.loads(frame["data"])}


async def test_success_stream_frames_conform(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    frames = parse_sse(r.text)
    assert frames
    for frame in frames:
        VALIDATOR.validate(as_event(frame))


async def test_failure_stream_frames_conform(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.fail_after_events = 1
    r = await client.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    frames = parse_sse(r.text)
    assert frames[-1]["event"] == "error"
    for frame in frames:
        VALIDATOR.validate(as_event(frame))


def test_schema_defines_all_seven_event_types() -> None:
    defined = {ref["$ref"].rsplit("/", 1)[1] for ref in SCHEMA["oneOf"]}
    assert defined == EVENT_TYPES


def test_unknown_event_is_rejected_by_schema() -> None:
    assert not VALIDATOR.is_valid({"event": "mystery", "data": {}})
    assert not VALIDATOR.is_valid({"event": "token", "data": {"index": 0}})


def test_tool_events_are_documented_as_informational() -> None:
    assert "tool_call and tool_result are informational" in SCHEMA["description"]


def test_usage_frame_with_unknown_token_counts_validates() -> None:
    event = {
        "event": "usage",
        "data": {"input_tokens": None, "output_tokens": None, "cost_usd": None},
    }
    VALIDATOR.validate(event)
    assert not VALIDATOR.is_valid(
        {"event": "usage", "data": {"input_tokens": -1, "output_tokens": 0, "cost_usd": None}}
    )


def test_schema_documents_that_token_counts_may_be_null() -> None:
    assert "token counts may be null" in SCHEMA["description"]
