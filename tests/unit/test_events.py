import json

import pytest

from ai_services.events import EventSequencer, StreamClosedError

PAYLOADS = {
    "token": {"index": 0, "text": "hi"},
    "tool_call": {"id": "c1", "name": "search_docs", "arguments": {"q": "x"}},
    "tool_result": {"id": "c1", "name": "search_docs", "status": "ok", "content": "r"},
    "citation": {"source_id": "s1", "title": "Doc"},
    "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": None},
    "done": {"finish_reason": "stop"},
    "error": {"code": "internal_error", "message": "boom"},
}


@pytest.mark.parametrize("event", [e for e in PAYLOADS if e not in ("done", "error")])
def test_each_event_type_encodes_to_a_frame(event: str) -> None:
    frame = EventSequencer().next(event, PAYLOADS[event])
    wire = frame.render()
    assert wire.startswith("id: 0\n") and f"event: {event}\n" in wire
    assert json.loads(frame.data) == PAYLOADS[event]


@pytest.mark.parametrize("event", ["done", "error"])
def test_terminal_events_encode(event: str) -> None:
    assert EventSequencer().next(event, PAYLOADS[event]).event == event


def test_sequence_numbers_start_at_zero_without_gaps() -> None:
    seq = EventSequencer()
    ids = [seq.next("token", {"index": i, "text": "x"}).id for i in range(4)]
    assert ids == [0, 1, 2, 3]


@pytest.mark.parametrize("terminal", ["done", "error"])
def test_nothing_after_terminal_event(terminal: str) -> None:
    seq = EventSequencer()
    seq.next(terminal, PAYLOADS[terminal])
    assert seq.closed
    with pytest.raises(StreamClosedError):
        seq.next("token", PAYLOADS["token"])


def test_unknown_event_and_bad_payload_rejected() -> None:
    seq = EventSequencer()
    with pytest.raises(ValueError):
        seq.next("nope", {})
    with pytest.raises(ValueError):
        seq.next("token", {"index": -1, "text": "x"})
    with pytest.raises(ValueError):
        seq.next("done", {"finish_reason": "weird"})


def test_usage_null_cost_is_valid() -> None:
    frame = EventSequencer().next("usage", PAYLOADS["usage"])
    assert json.loads(frame.data)["cost_usd"] is None


@pytest.mark.parametrize(
    "counts",
    [
        {"input_tokens": None, "output_tokens": 5},
        {"input_tokens": 3, "output_tokens": None},
        {"input_tokens": None, "output_tokens": None},
    ],
)
def test_usage_token_counts_may_be_unknown(counts: dict[str, int | None]) -> None:
    payload = {**counts, "cost_usd": None}
    frame = EventSequencer().next("usage", payload)
    assert json.loads(frame.data) == payload


def test_usage_negative_counts_still_rejected() -> None:
    with pytest.raises(ValueError):
        EventSequencer().next("usage", {"input_tokens": -1, "output_tokens": 0, "cost_usd": None})
    with pytest.raises(ValueError):
        EventSequencer().next("usage", {"input_tokens": 0, "output_tokens": -1, "cost_usd": None})
