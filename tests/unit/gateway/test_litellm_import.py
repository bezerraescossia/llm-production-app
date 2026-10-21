"""Importing the LiteLLM adapter must not load a .env file into the process environment."""

import subprocess
import sys
from pathlib import Path


def test_importing_the_adapter_does_not_read_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CANARY_FROM_DOTENV=leaked\n")
    code = (
        "import os; "
        "import ai_services.gateway.providers.litellm_provider; "
        "print(os.environ.get('CANARY_FROM_DOTENV'))"
    )
    env = {k: v for k, v in __import__("os").environ.items() if k != "LITELLM_MODE"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"


def test_the_model_map_comes_from_the_pinned_package_not_the_network(tmp_path: Path) -> None:
    code = (
        "import os; "
        "import ai_services.gateway.providers.litellm_provider as p; "
        "print(os.environ.get('LITELLM_LOCAL_MODEL_COST_MAP')); "
        "print(p.is_known_model('anthropic', 'claude-haiku-5-5'))"
    )
    env = {
        k: v
        for k, v in __import__("os").environ.items()
        if k not in ("LITELLM_MODE", "LITELLM_LOCAL_MODEL_COST_MAP")
    }
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "True"]
