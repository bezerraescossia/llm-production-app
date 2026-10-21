import pytest

from ai_services.gateway import Gateway
from ai_services.gateway.config import GatewayConfig, GenerationLimits, TemperatureLimit, TokenLimit
from ai_services.gateway.errors import GenerationSettingError
from ai_services.gateway.limits import resolve_generation
from ai_services.gateway.providers.litellm_provider import LiteLLMProvider
from ai_services.gateway.providers.stub import StubProvider
from ai_services.gateway.types import CompletionRequest, GenerationSettings
from tests.unit.gateway.helpers import SETTINGS, USER_MESSAGES, collect
from tests.unit.gateway.test_provider_conformance import FakeCompletion

LIMITS = GenerationLimits(
    max_output_tokens=TokenLimit(default=2048, ceiling=4096),
    temperature=TemperatureLimit(default=0.3, ceiling=1.0),
)


def test_defaults_apply_when_the_caller_passes_nothing() -> None:
    assert resolve_generation(LIMITS, GenerationSettings()) == GenerationSettings(2048, 0.3)


def test_a_caller_may_lower_a_setting() -> None:
    effective = resolve_generation(
        LIMITS, GenerationSettings(max_output_tokens=16, temperature=0.0)
    )
    assert effective == GenerationSettings(16, 0.0)


def test_a_value_equal_to_the_ceiling_is_allowed() -> None:
    assert resolve_generation(LIMITS, GenerationSettings(4096, 1.0)) == GenerationSettings(
        4096, 1.0
    )


@pytest.mark.parametrize(
    ("requested", "setting", "ceiling"),
    [
        (GenerationSettings(max_output_tokens=4097), "max_output_tokens", 4096),
        (GenerationSettings(temperature=1.5), "temperature", 1.0),
    ],
)
def test_a_value_above_the_ceiling_names_the_setting(
    requested: GenerationSettings, setting: str, ceiling: float
) -> None:
    with pytest.raises(GenerationSettingError) as exc:
        resolve_generation(LIMITS, requested)
    assert exc.value.setting == setting and exc.value.ceiling == ceiling
    assert setting in str(exc.value) and str(ceiling) in str(exc.value)


async def test_the_gateway_rejects_before_any_provider_is_contacted() -> None:
    from tests.unit.gateway.helpers import ScriptedProvider

    provider = ScriptedProvider([])
    gateway = Gateway(
        GatewayConfig.from_models({t: ["fake/m"] for t in ("small", "medium", "large")}),
        {"fake": provider},
    )
    with pytest.raises(GenerationSettingError, match="max_output_tokens"):
        await gateway.open(
            CompletionRequest("medium", USER_MESSAGES, GenerationSettings(max_output_tokens=10**6))
        )
    assert provider.calls == 0


async def test_an_answer_cut_by_the_maximum_length_finishes_with_length() -> None:
    gateway = Gateway(GatewayConfig.default(), {"stub": StubProvider()})
    request = CompletionRequest("medium", USER_MESSAGES, GenerationSettings(max_output_tokens=3))
    events = [e async for e in gateway.stream(request)]
    assert [k for k, _ in events].count("token") == 3
    assert events[-1] == ("done", {"finish_reason": "length"})


# --- models that only accept their default temperature (verified with LiteLLM's own mapping) ---


@pytest.mark.parametrize(
    ("provider", "model", "dropped"),
    [
        ("openai", "gpt-5-nano-2025-08-07", {"temperature"}),
        ("openai", "gpt-5-2025-08-07", {"temperature"}),
        ("anthropic", "claude-haiku-5-5", {"temperature"}),
        ("openai", "gpt-4o-mini", set()),
    ],
)
def test_default_check_asks_the_library_which_values_a_model_accepts(
    provider: str, model: str, dropped: set[str]
) -> None:
    assert LiteLLMProvider(provider, api_key=None).dropped_params(model) == dropped


async def test_dropped_parameters_are_omitted_from_the_call_explicitly() -> None:
    fake = FakeCompletion()
    provider = LiteLLMProvider(
        "openai", api_key="sk", completion=fake, params_check=lambda p, m: {"temperature"}
    )
    await collect(provider.stream("m", USER_MESSAGES, SETTINGS))
    assert "temperature" not in fake.kwargs and fake.kwargs["max_tokens"] == 100


async def test_supported_parameters_are_still_sent() -> None:
    fake = FakeCompletion()
    provider = LiteLLMProvider(
        "openai", api_key="sk", completion=fake, params_check=lambda p, m: set()
    )
    await collect(provider.stream("m", USER_MESSAGES, SETTINGS))
    assert fake.kwargs["temperature"] == 0.3


def test_the_check_is_cached_per_model() -> None:
    calls: list[str] = []

    def check(provider: str, model: str) -> set[str]:
        calls.append(model)
        return set()

    p = LiteLLMProvider("openai", api_key=None, params_check=check)
    p.dropped_params("m1")
    p.dropped_params("m1")
    p.dropped_params("m2")
    assert calls == ["m1", "m2"]
