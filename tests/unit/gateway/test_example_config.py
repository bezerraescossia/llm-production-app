from pathlib import Path

from ai_services.gateway.config import load_gateway_config
from ai_services.gateway.providers.litellm_provider import is_known_model

EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "gateway.example.yaml"


def test_the_example_config_loads_and_resolves_the_six_pinned_models() -> None:
    cfg = load_gateway_config(
        EXAMPLE,
        enabled_providers={"anthropic", "openai", "stub"},
        is_known_model=is_known_model,  # the real model map, so a stale id fails this test
    )
    names = {tier: [m.name for m in cfg.tiers[tier].models] for tier in cfg.tiers}
    assert names == {
        "small": ["anthropic/claude-haiku-5-5", "openai/gpt-5-nano-2025-08-07"],
        "medium": ["anthropic/claude-sonnet-5-5", "openai/gpt-5-mini-2025-08-07"],
        "large": ["anthropic/claude-opus-5-5", "openai/gpt-5-2025-08-07"],
    }
    assert cfg.default_tier == "medium"
    assert (cfg.timeouts.first_output_seconds, cfg.timeouts.pre_output_seconds) == (15, 45)
    assert (cfg.timeouts.idle_seconds, cfg.timeouts.total_seconds) == (20, 120)
    small = cfg.tiers["small"].generation
    assert (small.max_output_tokens.default, small.max_output_tokens.ceiling) == (2048, 4096)
    assert cfg.tiers["large"].generation.max_output_tokens.ceiling == 16384
