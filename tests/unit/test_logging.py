import asyncio
import io
import json

from ai_services.context import RequestContext, bind_identity, set_context
from ai_services.logging import configure_logging, get_logger


def lines(buf: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def fresh() -> io.StringIO:
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    return buf


def test_output_is_json_with_context_fields() -> None:
    buf = fresh()
    set_context(RequestContext(request_id="req-12345678", contract_version="1.0.0"))
    bind_identity("acme", "u-1")
    get_logger().info("hello", extra_field=1)
    [entry] = lines(buf)
    assert entry["event"] == "hello"
    assert entry["request_id"] == "req-12345678"
    assert entry["tenant_id"] == "acme"
    assert entry["user_id"] == "u-1"
    assert entry["extra_field"] == 1


def test_logging_without_context_still_works() -> None:
    buf = fresh()
    set_context(None)
    get_logger().info("startup")
    [entry] = lines(buf)
    assert entry["event"] == "startup" and "request_id" not in entry


def test_sensitive_keys_are_masked() -> None:
    buf = fresh()
    get_logger().info(
        "x",
        authorization="Bearer abc",
        service_token="tok",
        client_secret="s",
        db_password="p",
        nested={"api_token": "t", "safe": "ok"},
        output_tokens=5,
    )
    [entry] = lines(buf)
    assert entry["authorization"] == "[REDACTED]"
    assert entry["service_token"] == "[REDACTED]"
    assert entry["client_secret"] == "[REDACTED]"
    assert entry["db_password"] == "[REDACTED]"
    assert entry["nested"] == {"api_token": "[REDACTED]", "safe": "ok"}
    assert entry["output_tokens"] == 5  # token count is not a secret


async def test_concurrent_contexts_never_mix() -> None:
    buf = fresh()

    async def worker(tenant: str) -> None:
        set_context(RequestContext(request_id=f"req-{tenant}-0001", contract_version="1.0.0"))
        bind_identity(tenant, f"user-{tenant}")
        for _ in range(3):
            await asyncio.sleep(0)
            get_logger().info("tick")

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    for entry in lines(buf):
        tenant = str(entry["tenant_id"])
        assert entry["user_id"] == f"user-{tenant}"
        assert entry["request_id"] == f"req-{tenant}-0001"
