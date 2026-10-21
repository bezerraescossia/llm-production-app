"""Every configuration rule of data-model.md; each failure must name the offending entry."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from ai_services.gateway.config import (
    GatewayConfigError,
    load_gateway_config,
    load_gateway_config_text,
)

KNOWN = {
    ("anthropic", "claude-haiku-5-5"),
    ("anthropic", "claude-sonnet-5-5"),
    ("openai", "gpt-5-nano-2025-08-07"),
}
ENABLED = {"stub", "anthropic", "openai"}
BASE: dict[str, Any] = {
    "default_tier": "medium",
    "tiers": {t: {"models": ["stub/default"]} for t in ("small", "medium", "large")},
}


def is_known(provider: str, model_id: str) -> bool:
    return (provider, model_id) in KNOWN


def load(data: dict[str, Any], enabled: set[str] = ENABLED):  # type: ignore[no-untyped-def]
    return load_gateway_config_text(
        yaml.safe_dump(data), enabled_providers=enabled, is_known_model=is_known
    )


def changed(**top: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    data.update(top)
    return data


def with_models(tier: str, models: list[Any]) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    data["tiers"][tier]["models"] = models
    return data


def test_valid_configuration_resolves_ordered_models_and_defaults() -> None:
    cfg = load(with_models("small", ["anthropic/claude-haiku-5-5", "openai/gpt-5-nano-2025-08-07"]))
    assert [m.name for m in cfg.tiers["small"].models] == [
        "anthropic/claude-haiku-5-5",
        "openai/gpt-5-nano-2025-08-07",
    ]
    assert cfg.default_tier == "medium"
    assert cfg.timeouts.first_output_seconds == 15 and cfg.timeouts.pre_output_seconds == 45
    assert cfg.retry.max_attempts_per_model == 2 and cfg.cooldown.failure_threshold == 3


def test_changing_the_models_of_a_tier_changes_the_resolved_tier() -> None:
    first = load(with_models("small", ["anthropic/claude-haiku-5-5"]))
    second = load(with_models("small", ["openai/gpt-5-nano-2025-08-07"]))
    assert first.tiers["small"].models[0].name != second.tiers["small"].models[0].name


def test_loads_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "gateway.yaml"
    path.write_text(yaml.safe_dump(BASE))
    cfg = load_gateway_config(path, enabled_providers=ENABLED, is_known_model=is_known)
    assert set(cfg.tiers) == {"small", "medium", "large"}
    with pytest.raises(GatewayConfigError, match="missing.yaml"):
        load_gateway_config(
            tmp_path / "missing.yaml", enabled_providers=ENABLED, is_known_model=is_known
        )


def test_tiers_must_contain_small_medium_and_large() -> None:
    data = copy.deepcopy(BASE)
    del data["tiers"]["large"]
    with pytest.raises(GatewayConfigError, match=r"large"):
        load(data)


def test_empty_tier_is_refused_naming_the_tier() -> None:
    with pytest.raises(GatewayConfigError, match=r"tier 'small'.*no models"):
        load(with_models("small", []))


def test_duplicate_model_in_a_tier_is_refused_naming_it() -> None:
    with pytest.raises(GatewayConfigError, match=r"tier 'small'.*stub/default.*twice"):
        load(with_models("small", ["stub/default", "stub/default"]))


def test_unknown_provider_is_refused() -> None:
    with pytest.raises(GatewayConfigError, match=r"unknown provider 'acme'.*acme/m1"):
        load(with_models("small", ["acme/m1"]))


def test_malformed_model_entry_is_refused() -> None:
    with pytest.raises(GatewayConfigError, match=r"nonsense"):
        load(with_models("small", ["nonsense"]))


@pytest.mark.parametrize(
    "entry", ["anthropic/claude-haiku-latest", "openai/gpt-5-chat-latest", "anthropic/latest"]
)
def test_moving_aliases_are_refused(entry: str) -> None:
    with pytest.raises(GatewayConfigError, match=r"moving alias.*" + entry.split("/")[1]):
        load(with_models("small", [entry]))


def test_model_unknown_to_the_library_is_refused_unless_overridden() -> None:
    with pytest.raises(GatewayConfigError, match=r"claude-new-9"):
        load(with_models("small", ["anthropic/claude-new-9"]))
    cfg = load(
        with_models("small", [{"model": "anthropic/claude-new-9", "max_input_tokens": 1000}])
    )
    assert cfg.tiers["small"].models[0].max_input_tokens == 1000


def test_unknown_stub_model_is_refused() -> None:
    with pytest.raises(GatewayConfigError, match=r"stub/nope"):
        load(with_models("small", ["stub/nope"]))


def test_provider_without_a_credential_is_refused_naming_the_variable() -> None:
    data = with_models("small", ["anthropic/claude-haiku-5-5"])
    with pytest.raises(GatewayConfigError, match=r"ANTHROPIC_API_KEY.*anthropic/claude-haiku-5-5"):
        load(data, enabled={"stub", "openai"})
    data = with_models("small", ["openai/gpt-5-nano-2025-08-07"])
    with pytest.raises(GatewayConfigError, match=r"OPENAI_API_KEY"):
        load(data, enabled={"stub", "anthropic"})


def test_stub_needs_no_credential() -> None:
    assert load(BASE, enabled={"stub"}).default_tier == "medium"


def test_default_tier_must_be_configured() -> None:
    with pytest.raises(GatewayConfigError, match=r"default_tier 'huge'"):
        load(changed(default_tier="huge"))


@pytest.mark.parametrize(
    ("timeouts", "message"),
    [
        ({"first_output_seconds": 0}, "first_output_seconds"),
        ({"idle_seconds": -1}, "idle_seconds"),
        ({"first_output_seconds": 50, "pre_output_seconds": 45}, "first_output_seconds"),
        ({"pre_output_seconds": 130, "total_seconds": 120}, "pre_output_seconds"),
        ({"idle_seconds": 130, "total_seconds": 120}, "idle_seconds"),
    ],
)
def test_timeout_rules(timeouts: dict[str, float], message: str) -> None:
    with pytest.raises(GatewayConfigError, match=message):
        load(changed(timeouts=timeouts))


@pytest.mark.parametrize(
    ("section", "values", "message"),
    [
        ("retry", {"max_attempts_per_model": 0}, "max_attempts_per_model"),
        ("retry", {"backoff_base_seconds": 0}, "backoff_base_seconds"),
        ("retry", {"backoff_max_seconds": -1}, "backoff_max_seconds"),
        ("cooldown", {"failure_threshold": 0}, "failure_threshold"),
        ("cooldown", {"seconds": 0}, "seconds"),
    ],
)
def test_retry_and_cooldown_must_be_positive(
    section: str, values: dict[str, float], message: str
) -> None:
    with pytest.raises(GatewayConfigError, match=message):
        load(changed(**{section: values}))


def generation(**g: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    data["tiers"]["small"]["generation"] = g
    return data


@pytest.mark.parametrize(
    ("gen", "message"),
    [
        ({"max_output_tokens": {"default": 5000, "ceiling": 4096}}, "max_output_tokens"),
        ({"max_output_tokens": {"default": 0, "ceiling": 4096}}, "max_output_tokens"),
        ({"temperature": {"default": 0.9, "ceiling": 0.5}}, "temperature"),
        ({"temperature": {"default": 0.3, "ceiling": 2.5}}, "temperature"),
        ({"temperature": {"default": -0.1, "ceiling": 1.0}}, "temperature"),
    ],
)
def test_generation_limit_rules(gen: dict[str, Any], message: str) -> None:
    with pytest.raises(GatewayConfigError, match=message):
        load(generation(**gen))


def test_unknown_keys_are_refused() -> None:
    with pytest.raises(GatewayConfigError, match="surprise"):
        load(changed(surprise=True))


def test_invalid_yaml_is_refused() -> None:
    with pytest.raises(GatewayConfigError):
        load_gateway_config_text(
            "tiers: [unclosed", enabled_providers=ENABLED, is_known_model=is_known
        )
