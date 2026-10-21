"""Read the served contract version from the committed OpenAPI file."""

from pathlib import Path

import yaml

DEFAULT_CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contracts" / "v1"


def load_contract_version(contract_dir: Path = DEFAULT_CONTRACT_DIR) -> str:
    with (contract_dir / "openapi.yaml").open() as handle:
        document = yaml.safe_load(handle)
    return str(document["info"]["version"])
