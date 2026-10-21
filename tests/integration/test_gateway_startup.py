from pathlib import Path

import httpx
import pytest
import yaml
from asgi_lifespan import LifespanManager

from ai_services.config import Settings
from ai_services.main import create_app
from tests.conftest import TOKEN_A, VALID_BODY, auth, parse_sse

SECRET_KEY = "sk-ant-this-secret-must-never-be-logged"


def tiers(**overrides: list[str]) -> dict[str, dict[str, list[str]]]:
    models = {"small": ["stub/default"], "medium": ["stub/default"], "large": ["stub/default"]}
    models.update(overrides)
    return {t: {"models": m} for t, m in models.items()}


def write(tmp_path: Path, **overrides: list[str]) -> Path:
    path = tmp_path / "gateway.yaml"
    path.write_text(yaml.safe_dump({"default_tier": "medium", "tiers": tiers(**overrides)}))
    return path


def settings(path: Path | None = None, **extra: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        service_tokens=[TOKEN_A],
        gateway_config=path,
        **extra,
    )


def test_an_invalid_configuration_stops_startup_naming_the_entry(tmp_path: Path) -> None:
    path = write(tmp_path, small=["stub/default", "stub/default"])
    with pytest.raises(SystemExit) as exc:
        create_app(settings(path))
    assert "small" in str(exc.value) and "stub/default" in str(exc.value)


def test_a_missing_credential_stops_startup_naming_the_variable(tmp_path: Path) -> None:
    path = write(tmp_path, small=["anthropic/claude-haiku-5-5"])
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        create_app(settings(path))


def test_a_moving_alias_stops_startup(tmp_path: Path) -> None:
    path = write(tmp_path, small=["anthropic/claude-haiku-latest"])
    with pytest.raises(SystemExit, match="claude-haiku-latest"):
        create_app(settings(path, anthropic_api_key=SECRET_KEY))


def test_unset_gateway_config_uses_the_builtin_stub_configuration() -> None:
    app = create_app(settings())
    models = {
        t: [m.name for m in tier.models] for t, tier in app.state.gateway.config.tiers.items()
    }
    assert models == {t: ["stub/default"] for t in ("small", "medium", "large")}


async def test_a_valid_file_decides_which_models_serve_the_tiers(tmp_path: Path) -> None:
    path = write(tmp_path, medium=["stub/empty"])
    app = create_app(settings(path))
    assert app.state.gateway.config.tiers["medium"].models[0].name == "stub/empty"
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/v1/chat/stream", json=VALID_BODY, headers=auth())
    assert [f["event"] for f in parse_sse(r.text)] == ["usage", "done"]


def test_startup_logs_the_mapping_but_never_a_credential(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        small=["anthropic/claude-haiku-5-5"],
        medium=["anthropic/claude-sonnet-5-5"],
    )
    app = create_app(settings(path, anthropic_api_key=SECRET_KEY))
    assert app.state.gateway.config.tiers["small"].models[0].name == "anthropic/claude-haiku-5-5"
    logs = capsys.readouterr().out
    assert "gateway_ready" in logs and "anthropic/claude-sonnet-5-5" in logs
    assert SECRET_KEY not in logs
