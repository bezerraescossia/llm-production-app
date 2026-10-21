import pytest
from pydantic import ValidationError

from ai_services.schemas import IDENTIFIER_PATTERN, REQUEST_ID_PATTERN, ChatRequest

U = {"role": "user", "content": "hi"}
A = {"role": "assistant", "content": "yo"}


def test_valid_request() -> None:
    assert len(ChatRequest.model_validate({"messages": [A, U]}).messages) == 2


def test_empty_messages_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": []})


def test_more_than_100_messages_rejected() -> None:
    ChatRequest.model_validate({"messages": [U] * 100})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [U] * 101})


def test_role_must_be_user_or_assistant() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [{"role": "system", "content": "x"}, U]})


def test_content_length_bounds() -> None:
    ChatRequest.model_validate({"messages": [{"role": "user", "content": "x" * 32000}]})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [{"role": "user", "content": "x" * 32001}]})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [{"role": "user", "content": ""}]})


def test_last_message_must_be_user() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [U, A]})


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [U], "extra": 1})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [{**U, "name": "x"}]})


@pytest.mark.parametrize("value", ["acme", "a.b_c:d@e-f", "x" * 128])
def test_identifier_accepts(value: str) -> None:
    assert IDENTIFIER_PATTERN.fullmatch(value)


@pytest.mark.parametrize("value", ["", "x" * 129, "has space", "new\nline", "a/b", "über"])
def test_identifier_rejects(value: str) -> None:
    assert not IDENTIFIER_PATTERN.fullmatch(value)


@pytest.mark.parametrize("value", ["abcdefgh", "req-1234.ab_cd", "x" * 128])
def test_request_id_accepts(value: str) -> None:
    assert REQUEST_ID_PATTERN.fullmatch(value)


@pytest.mark.parametrize("value", ["short", "x" * 129, "has space1", "bad:colon1"])
def test_request_id_rejects(value: str) -> None:
    assert not REQUEST_ID_PATTERN.fullmatch(value)
