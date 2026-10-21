"""Settings loaded from the environment. Fails fast, naming the offending variable."""

import re
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_TOKEN_LENGTH = 32
MAX_TOKENS = 2
MAX_MESSAGES_CAP = 100  # contract maxItems; the limit may only be lowered
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_DEPENDENCY = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)=(?P<host>[A-Za-z0-9_.-]+):(?P<port>\d{1,5})$")


class Dependency(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    host: str
    port: int


def _split(value: Any) -> Any:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_tokens: Annotated[list[str], NoDecode]
    readiness_dependencies: Annotated[list[Dependency], NoDecode] = []
    max_request_bytes: int = Field(default=262144, gt=0)
    max_messages: int = Field(default=100, gt=0, le=MAX_MESSAGES_CAP)
    shutdown_grace_seconds: int = Field(default=20, gt=0)
    placeholder_token_delay_ms: int = Field(default=0, ge=0)
    log_level: str = "INFO"
    enable_docs: bool = False  # Swagger UI at /v1/docs; for development, off by default
    gateway_config: Path | None = None  # YAML with tiers and models; built-in stub config if unset
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    @field_validator("gateway_config", "anthropic_api_key", "openai_api_key", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("service_tokens", mode="before")
    @classmethod
    def _tokens_from_str(cls, value: Any) -> Any:
        return _split(value)

    @field_validator("service_tokens")
    @classmethod
    def _tokens_valid(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= MAX_TOKENS:
            raise ValueError(f"expected 1 to {MAX_TOKENS} tokens, got {len(value)}")
        if any(len(token) < MIN_TOKEN_LENGTH for token in value):
            raise ValueError(f"each token must be at least {MIN_TOKEN_LENGTH} characters")
        return value

    @field_validator("readiness_dependencies", mode="before")
    @classmethod
    def _dependencies_from_str(cls, value: Any) -> Any:
        parts = _split(value)
        if not isinstance(parts, list):
            return parts
        parsed: list[Any] = []
        for part in parts:
            if not isinstance(part, str):
                parsed.append(part)
                continue
            match = _DEPENDENCY.match(part)
            if match is None:
                raise ValueError(f"invalid dependency {part!r}, expected name=host:port")
            parsed.append(
                {"name": match["name"], "host": match["host"], "port": int(match["port"])}
            )
        return parsed

    @field_validator("log_level")
    @classmethod
    def _level_valid(cls, value: str) -> str:
        level = value.upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"log level must be one of {sorted(LOG_LEVELS)}")
        return level


def load_settings() -> Settings:
    """Load settings from the environment, or exit with a message naming each bad variable."""
    try:
        return Settings()  # pyright: ignore[reportCallIssue]  # values come from the environment
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p).upper() for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise SystemExit(f"Invalid configuration: {problems}") from None
