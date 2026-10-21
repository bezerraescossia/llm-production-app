import httpx

from tests.contract.helpers import load_openapi


async def test_contract_route_returns_version_without_credentials(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/v1/contract")
    assert r.status_code == 200
    assert r.json() == {"version": load_openapi()["info"]["version"]}
    assert r.headers["x-contract-version"] == r.json()["version"]
