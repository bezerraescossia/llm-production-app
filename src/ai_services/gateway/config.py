"""Gateway configuration: models, YAML loading and the startup validation rules."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_services.gateway.providers.stub import STUB_MODELS

PROVIDERS = ("anthropic", "openai", "stub")
CREDENTIAL_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
REQUIRED_TIERS = ("small", "medium", "large")


class GatewayConfigError(ValueError):
    """An invalid gateway configuration. The message names the offending entry, never a secret."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelCandidate(_Model):
    provider: str
    model_id: str
    max_input_tokens: int = 100_000

    @property
    def name(self) -> str:
        return f"{self.provider}/{self.model_id}"

    @classmethod
    def parse(cls, entry: str) -> "ModelCandidate":
        provider, _, model_id = entry.partition("/")
        return cls(provider=provider, model_id=model_id)


class TokenLimit(_Model):
    default: int
    ceiling: int

    @model_validator(mode="after")
    def _check(self) -> "TokenLimit":
        if not 0 < self.default <= self.ceiling:
            raise ValueError(
                "max_output_tokens needs 0 < default <= ceiling, "
                f"got {self.default} and {self.ceiling}"
            )
        return self


class TemperatureLimit(_Model):
    default: float
    ceiling: float

    @model_validator(mode="after")
    def _check(self) -> "TemperatureLimit":
        if not 0 <= self.default <= self.ceiling <= 2:
            raise ValueError(
                "temperature needs 0 <= default <= ceiling <= 2, "
                f"got {self.default} and {self.ceiling}"
            )
        return self


class GenerationLimits(_Model):
    max_output_tokens: TokenLimit = TokenLimit(default=2048, ceiling=4096)
    temperature: TemperatureLimit = TemperatureLimit(default=0.3, ceiling=1.0)


class Tier(_Model):
    models: list[ModelCandidate]
    generation: GenerationLimits = GenerationLimits()


class Timeouts(_Model):
    first_output_seconds: float = Field(default=15, gt=0)
    pre_output_seconds: float = Field(default=45, gt=0)
    idle_seconds: float = Field(default=20, gt=0)
    total_seconds: float = Field(default=120, gt=0)

    @model_validator(mode="after")
    def _ordering(self) -> "Timeouts":
        if self.first_output_seconds > self.pre_output_seconds:
            raise ValueError(
                f"first_output_seconds ({self.first_output_seconds}) must not exceed "
                f"pre_output_seconds ({self.pre_output_seconds})"
            )
        if self.pre_output_seconds > self.total_seconds:
            raise ValueError(
                f"pre_output_seconds ({self.pre_output_seconds}) must not exceed "
                f"total_seconds ({self.total_seconds})"
            )
        if self.idle_seconds > self.total_seconds:
            raise ValueError(
                f"idle_seconds ({self.idle_seconds}) must not exceed "
                f"total_seconds ({self.total_seconds})"
            )
        return self


class RetryPolicy(_Model):
    max_attempts_per_model: int = Field(default=2, gt=0)
    backoff_base_seconds: float = Field(default=0.25, gt=0)
    backoff_max_seconds: float = Field(default=2.0, gt=0)


class CooldownPolicy(_Model):
    failure_threshold: int = Field(default=3, gt=0)
    seconds: float = Field(default=30, gt=0)


class GatewayConfig(_Model):
    default_tier: str = "medium"
    timeouts: Timeouts = Timeouts()
    retry: RetryPolicy = RetryPolicy()
    cooldown: CooldownPolicy = CooldownPolicy()
    tiers: dict[str, Tier]

    @classmethod
    def from_models(
        cls, tiers: Mapping[str, Sequence[str]], default_tier: str = "medium"
    ) -> "GatewayConfig":
        """Build a config from `{tier: ["provider/model", ...]}` with default policies."""
        return cls(
            default_tier=default_tier,
            tiers={
                name: Tier(models=[ModelCandidate.parse(entry) for entry in entries])
                for name, entries in tiers.items()
            },
        )

    @classmethod
    def default(cls) -> "GatewayConfig":
        """Built-in configuration: every tier is served by the stub (no credentials needed)."""
        return cls.from_models({t: ["stub/default"] for t in ("small", "medium", "large")})


def _split_entry(entry: str) -> tuple[str, str]:
    provider, sep, model_id = entry.partition("/")
    if not sep or not provider or not model_id:
        raise GatewayConfigError(f"model entry '{entry}' must look like provider/model-id")
    return provider, model_id


def _prepare(data: Any) -> tuple[dict[str, Any], set[str]]:
    """Turn the models of each tier into candidate dicts; remember which carry an explicit limit."""
    if not isinstance(data, dict):
        raise GatewayConfigError("the configuration must be a mapping")
    data = dict(data)
    overrides: set[str] = set()
    tiers = data.get("tiers")
    if isinstance(tiers, dict):
        prepared: dict[str, Any] = {}
        for tier_name, tier in tiers.items():
            if not isinstance(tier, dict):
                raise GatewayConfigError(f"tier '{tier_name}' must be a mapping")
            tier = dict(tier)
            models: list[Any] = []
            for entry in tier.get("models") or []:
                if isinstance(entry, str):
                    provider, model_id = _split_entry(entry)
                    models.append({"provider": provider, "model_id": model_id})
                elif isinstance(entry, dict) and "model" in entry:
                    provider, model_id = _split_entry(str(entry["model"]))
                    candidate: dict[str, Any] = {"provider": provider, "model_id": model_id}
                    if "max_input_tokens" in entry:
                        candidate["max_input_tokens"] = entry["max_input_tokens"]
                        overrides.add(f"{provider}/{model_id}")
                    models.append(candidate)
                else:
                    raise GatewayConfigError(f"tier '{tier_name}': invalid model entry {entry!r}")
            tier["models"] = models
            prepared[tier_name] = tier
        data["tiers"] = prepared
    return data, overrides


def load_gateway_config_text(
    text: str,
    *,
    enabled_providers: set[str],
    is_known_model: Callable[[str, str], bool],
) -> GatewayConfig:
    """Parse and validate YAML. Raises GatewayConfigError naming the offending entry."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GatewayConfigError(f"the configuration is not valid YAML: {exc}") from None
    data, overrides = _prepare(raw)
    try:
        config = GatewayConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise GatewayConfigError(problems) from None
    _validate(config, overrides, enabled_providers, is_known_model)
    return config


def load_gateway_config(
    path: Path,
    *,
    enabled_providers: set[str],
    is_known_model: Callable[[str, str], bool],
) -> GatewayConfig:
    try:
        text = path.read_text()
    except OSError as exc:
        raise GatewayConfigError(f"cannot read {path}: {exc.strerror}") from None
    return load_gateway_config_text(
        text, enabled_providers=enabled_providers, is_known_model=is_known_model
    )


def _validate(
    config: GatewayConfig,
    overrides: set[str],
    enabled_providers: set[str],
    is_known_model: Callable[[str, str], bool],
) -> None:
    missing = [t for t in REQUIRED_TIERS if t not in config.tiers]
    if missing:
        raise GatewayConfigError(
            "tiers must contain `small`, `medium` and `large`; missing: " + ", ".join(missing)
        )
    for tier_name, tier in config.tiers.items():
        if not tier.models:
            raise GatewayConfigError(f"tier '{tier_name}' has no models")
        seen: set[str] = set()
        for model in tier.models:
            name = model.name
            if name in seen:
                raise GatewayConfigError(f"tier '{tier_name}' lists '{name}' twice")
            seen.add(name)
            if model.provider not in PROVIDERS:
                raise GatewayConfigError(
                    f"tier '{tier_name}': unknown provider '{model.provider}' in '{name}' "
                    f"(expected one of {', '.join(PROVIDERS)})"
                )
            if model.model_id.endswith("latest"):
                raise GatewayConfigError(
                    f"tier '{tier_name}': moving alias refused, use an exact model id "
                    f"instead of '{name}'"
                )
            if model.provider == "stub":
                if model.model_id not in STUB_MODELS:
                    raise GatewayConfigError(f"tier '{tier_name}': unknown stub model '{name}'")
                continue
            if name not in overrides and not is_known_model(model.provider, model.model_id):
                raise GatewayConfigError(
                    f"tier '{tier_name}': model '{name}' is not in the model library; "
                    "add max_input_tokens to the entry to use it anyway"
                )
            if model.provider not in enabled_providers:
                raise GatewayConfigError(
                    f"tier '{tier_name}': provider '{model.provider}' has no credential "
                    f"(set {CREDENTIAL_VARIABLES[model.provider]}) for '{name}'"
                )
    if config.default_tier not in config.tiers:
        raise GatewayConfigError(
            f"default_tier '{config.default_tier}' is not one of the configured tiers "
            f"({', '.join(sorted(config.tiers))})"
        )
