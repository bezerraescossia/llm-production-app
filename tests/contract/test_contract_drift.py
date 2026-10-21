"""The app's generated OpenAPI must stay structurally equal to the committed contract."""

from typing import Any

import httpx
from fastapi import FastAPI

from tests.contract.helpers import load_openapi

KEYS = ("type", "pattern", "minLength", "maxLength", "minItems", "maxItems", "minimum")


def resolve(schema: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        node: Any = doc
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def project(schema: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Reduce a schema to the constraints a client depends on, ignoring titles and wording."""
    s = resolve(schema, doc)
    branches = s.get("anyOf")
    if branches and len(branches) == 2 and any(b.get("type") == "null" for b in branches):
        non_null = next(b for b in branches if b.get("type") != "null")
        s = {**{k: v for k, v in s.items() if k != "anyOf"}, **resolve(non_null, doc)}
    out: dict[str, Any] = {k: s[k] for k in KEYS if k in s}
    if "enum" in s:
        out["enum"] = sorted(s["enum"])
    if "const" in s:
        out["enum"] = [s["const"]]
    if "required" in s:
        out["required"] = sorted(s["required"])
    extra = s.get("additionalProperties")
    if extra in (True, {}):
        out["additionalProperties"] = True
    elif extra is False:
        out["additionalProperties"] = False
    if "properties" in s:
        out["properties"] = {k: project(v, doc) for k, v in s["properties"].items()}
    if "items" in s:
        out["items"] = project(s["items"], doc)
    return out


def operations(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (path, method): op
        for path, ops in doc["paths"].items()
        for method, op in ops.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }


def responses(op: dict[str, Any], doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for status, response in op["responses"].items():
        resolved[status] = resolve(response, doc) if "$ref" in response else response
    return resolved


def parameters(op: dict[str, Any], doc: dict[str, Any]) -> set[tuple[str, str, bool]]:
    return {
        (p["name"], p["in"], bool(p.get("required", False)))
        for p in (resolve(p, doc) for p in op.get("parameters", []))
    }


def test_paths_methods_and_operation_ids_match(app: FastAPI) -> None:
    contract, generated = load_openapi(), app.openapi()
    contract_ops, generated_ops = operations(contract), operations(generated)
    assert set(generated_ops) == set(contract_ops)
    for key, op in contract_ops.items():
        assert generated_ops[key]["operationId"] == op["operationId"], key


def test_every_route_is_under_the_major_version_prefix(app: FastAPI) -> None:
    assert all(path.startswith("/v1/") for path in app.openapi()["paths"])


def test_status_codes_content_types_and_schemas_match(app: FastAPI) -> None:
    contract, generated = load_openapi(), app.openapi()
    generated_ops = operations(generated)
    for key, op in operations(contract).items():
        want, got = responses(op, contract), responses(generated_ops[key], generated)
        assert set(got) == set(want), f"{key}: statuses differ"
        for status, response in want.items():
            want_content = response.get("content", {})
            got_content = got[status].get("content", {})
            assert set(got_content) == set(want_content), f"{key} {status}: content types differ"
            for media, body in want_content.items():
                if media == "application/json":
                    assert project(got_content[media]["schema"], generated) == project(
                        body["schema"], contract
                    ), f"{key} {status}: schema differs"


def test_request_body_and_parameters_match(app: FastAPI) -> None:
    contract, generated = load_openapi(), app.openapi()
    generated_ops = operations(generated)
    for key, op in operations(contract).items():
        assert parameters(generated_ops[key], generated) == parameters(op, contract), key
        want_body = op.get("requestBody")
        got_body = generated_ops[key].get("requestBody")
        assert bool(got_body) == bool(want_body), key
        if want_body:
            assert bool(got_body["required"]) == bool(want_body["required"])
            assert project(got_body["content"]["application/json"]["schema"], generated) == project(
                want_body["content"]["application/json"]["schema"], contract
            )


async def test_served_version_matches_contract(app: FastAPI, client: httpx.AsyncClient) -> None:
    version = load_openapi()["info"]["version"]
    assert app.openapi()["info"]["version"] == version
    r = await client.get("/v1/contract")
    assert r.json()["version"] == version and r.headers["x-contract-version"] == version
