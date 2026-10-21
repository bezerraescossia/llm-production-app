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
