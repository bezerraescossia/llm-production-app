from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_services.config import Settings, load_settings

GOOD = "g" * 32


def make(**env: Any) -> Settings:
    return Settings(_env_file=None, **env)  # type: ignore[call-arg]


def test_missing_service_tokens_fails_naming_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here, so only the environment is consulted
    monkeypatch.delenv("SERVICE_TOKENS", raising=False)
    with pytest.raises(SystemExit) as exc:
        load_settings()
    assert "SERVICE_TOKENS" in str(exc.value)


def test_short_token_rejected() -> None:
    with pytest.raises(ValidationError):
        make(service_tokens="short")


def test_more_than_two_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        make(service_tokens=",".join(c * 32 for c in "abc"))


def test_one_or_two_tokens_accepted() -> None:
    assert make(service_tokens=GOOD).service_tokens == [GOOD]
    two = make(service_tokens=f"{GOOD}, {'h' * 32}")
    assert two.service_tokens == [GOOD, "h" * 32]


def test_defaults() -> None:
    s = make(service_tokens=GOOD)
    assert s.max_request_bytes == 262144
    assert s.max_messages == 100
    assert s.shutdown_grace_seconds == 20
    assert s.placeholder_token_delay_ms == 0
    assert s.log_level == "INFO"
    assert s.readiness_dependencies == []


def test_max_messages_cannot_exceed_contract_limit() -> None:
    with pytest.raises(ValidationError):
        make(service_tokens=GOOD, max_messages=101)


def test_readiness_dependencies_parse() -> None:
    s = make(service_tokens=GOOD, readiness_dependencies="postgres=db:5432, redis=cache:6379")
    assert [(d.name, d.host, d.port) for d in s.readiness_dependencies] == [
        ("postgres", "db", 5432),
        ("redis", "cache", 6379),
    ]


def test_bad_dependency_entry_rejected() -> None:
    with pytest.raises(ValidationError):
        make(service_tokens=GOOD, readiness_dependencies="nonsense")


def test_non_positive_limits_rejected() -> None:
    with pytest.raises(ValidationError):
        make(service_tokens=GOOD, max_request_bytes=0)


def test_gateway_settings_default_to_unset() -> None:
    s = make(service_tokens=GOOD)
    assert s.gateway_config is None
    assert s.anthropic_api_key is None and s.openai_api_key is None


def test_empty_gateway_settings_are_treated_as_unset() -> None:
    s = make(service_tokens=GOOD, gateway_config="", anthropic_api_key="", openai_api_key="")
    assert s.gateway_config is None
    assert s.anthropic_api_key is None and s.openai_api_key is None


def test_gateway_settings_accept_values_and_hide_secrets() -> None:
    s = make(
        service_tokens=GOOD,
        gateway_config="config/gateway.local.yaml",
        anthropic_api_key="sk-ant-very-secret-value",
        openai_api_key="sk-openai-very-secret-value",
    )
    assert str(s.gateway_config) == "config/gateway.local.yaml"
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-very-secret-value"
    shown = repr(s) + str(s)
    assert "very-secret-value" not in shown
