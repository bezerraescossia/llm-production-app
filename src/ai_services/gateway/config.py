"""Gateway configuration models. YAML loading and validation rules are added in US2."""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict


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


class TemperatureLimit(_Model):
    default: float
    ceiling: float


class GenerationLimits(_Model):
    max_output_tokens: TokenLimit = TokenLimit(default=2048, ceiling=4096)
    temperature: TemperatureLimit = TemperatureLimit(default=0.3, ceiling=1.0)


class Tier(_Model):
    models: list[ModelCandidate]
    generation: GenerationLimits = GenerationLimits()


class Timeouts(_Model):
    first_output_seconds: float = 15
    pre_output_seconds: float = 45
    idle_seconds: float = 20
    total_seconds: float = 120


class RetryPolicy(_Model):
    max_attempts_per_model: int = 2
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 2.0


class CooldownPolicy(_Model):
    failure_threshold: int = 3
    seconds: float = 30


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
