"""Builds the gateway at startup: validates configuration, creates providers, logs the mapping."""

from ai_services.config import Settings
from ai_services.gateway.config import GatewayConfig, GatewayConfigError, load_gateway_config
from ai_services.gateway.orchestrator import Gateway
from ai_services.gateway.providers.base import Provider
from ai_services.gateway.providers.litellm_provider import (
    LiteLLMProvider,
    is_known_model,
    library_input_limit,
)
from ai_services.gateway.providers.stub import StubProvider
from ai_services.logging import get_logger

log = get_logger(__name__)


def enabled_providers(settings: Settings) -> set[str]:
    """Providers that can be used: the stub always, a real one only with a credential."""
    enabled = {"stub"}
    if settings.anthropic_api_key is not None:
        enabled.add("anthropic")
    if settings.openai_api_key is not None:
        enabled.add("openai")
    return enabled


def build_gateway(
    settings: Settings, stub: StubProvider, gateway_config: GatewayConfig | None = None
) -> Gateway:
    """Load and validate the configuration, or exit with a message naming the offending entry."""
    enabled = enabled_providers(settings)
    if gateway_config is None:
        if settings.gateway_config is None:
            gateway_config = GatewayConfig.default()
        else:
            try:
                gateway_config = load_gateway_config(
                    settings.gateway_config,
                    enabled_providers=enabled,
                    is_known_model=is_known_model,
                )
            except GatewayConfigError as exc:
                raise SystemExit(f"Invalid gateway configuration: {exc}") from None

    providers: dict[str, Provider] = {"stub": stub}
    lite: dict[str, LiteLLMProvider] = {}
    for name, key in (
        ("anthropic", settings.anthropic_api_key),
        ("openai", settings.openai_api_key),
    ):
        if key is not None:
            lite[name] = LiteLLMProvider(name, key.get_secret_value())
            providers[name] = lite[name]

    # Say, once per model, which generation parameters it does not accept (never silently).
    for tier in gateway_config.tiers.values():
        for model in tier.models:
            provider = lite.get(model.provider)
            if provider is not None and (dropped := provider.dropped_params(model.model_id)):
                log.info("gateway_params_dropped", model=model.name, params=sorted(dropped))

    log.info(
        "gateway_ready",
        default_tier=gateway_config.default_tier,
        tiers={name: [m.name for m in t.models] for name, t in gateway_config.tiers.items()},
    )
    return Gateway(
        gateway_config,
        providers,
        input_limit=lambda m: m.max_input_tokens or library_input_limit(m.provider, m.model_id),
    )
