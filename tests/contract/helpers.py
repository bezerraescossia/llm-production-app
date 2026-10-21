"""Helpers shared by the contract tests."""

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contracts" / "v1"


def load_openapi() -> dict[str, Any]:
    with (CONTRACT_DIR / "openapi.yaml").open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    return loaded


def load_events_schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CONTRACT_DIR / "events.schema.json").read_text())
    return loaded


def schema_validator(openapi: dict[str, Any], schema: dict[str, Any]) -> Draft202012Validator:
    """Validator for a schema that may use $ref into the document's components."""
    return Draft202012Validator({**schema, "components": openapi["components"]})


def response_schema(openapi: dict[str, Any], path: str, method: str, status: int) -> dict[str, Any]:
    response = openapi["paths"][path][method]["responses"][str(status)]
    if "$ref" in response:
        response = openapi["components"]["responses"][response["$ref"].rsplit("/", 1)[1]]
    schema: dict[str, Any] = response["content"]["application/json"]["schema"]
    return schema
