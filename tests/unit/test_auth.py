import pytest

from ai_services.auth import Identity, extract_bearer, token_is_valid, validate_identity
from ai_services.errors import ErrorCode, ServiceError

TOK_A = "a" * 32
TOK_B = "b" * 32


def test_extract_bearer() -> None:
    assert extract_bearer("Bearer abc") == "abc"
    assert extract_bearer("bearer abc") == "abc"
    for bad in (None, "", "Basic abc", "Bearer", "Bearer ", "abc"):
        assert extract_bearer(bad) is None


def test_valid_token_accepted_and_unknown_rejected() -> None:
    assert token_is_valid(TOK_A, [TOK_A])
    assert not token_is_valid("c" * 32, [TOK_A])
    assert not token_is_valid(None, [TOK_A])
    assert not token_is_valid("", [TOK_A])


def test_both_tokens_accepted_during_rotation_then_old_rejected() -> None:
    assert token_is_valid(TOK_A, [TOK_A, TOK_B])
    assert token_is_valid(TOK_B, [TOK_A, TOK_B])
    assert not token_is_valid(TOK_A, [TOK_B])  # old token removed after rotation


def test_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return a == b

    monkeypatch.setattr("ai_services.auth.hmac.compare_digest", spy)
    assert token_is_valid(TOK_B, [TOK_A, TOK_B])
    assert len(calls) == 2  # every configured token is compared, no early exit


def headers(**kw: str) -> dict[str, str]:
    base = {"x-tenant-id": "acme", "x-user-id": "u-1"}
    base.update({k.replace("_", "-"): v for k, v in kw.items()})
    return base


def test_valid_identity() -> None:
    assert validate_identity(headers()) == Identity(tenant_id="acme", user_id="u-1")


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"x_tenant_id": ""}, "X-Tenant-Id"),
        ({"x_tenant_id": "x" * 129}, "X-Tenant-Id"),
        ({"x_tenant_id": "bad value"}, "X-Tenant-Id"),
        ({"x_user_id": ""}, "X-User-Id"),
        ({"x_user_id": "a/b"}, "X-User-Id"),
        ({"x_user_id": "x" * 129}, "X-User-Id"),
    ],
)
def test_invalid_identity_names_the_header(override: dict[str, str], field: str) -> None:
    with pytest.raises(ServiceError) as exc:
        validate_identity(headers(**override))
    assert exc.value.code is ErrorCode.INVALID_IDENTITY
    assert exc.value.details == {"field": field}


@pytest.mark.parametrize("missing", ["x-tenant-id", "x-user-id"])
def test_missing_identity_names_the_header(missing: str) -> None:
    h = headers()
    del h[missing]
    with pytest.raises(ServiceError) as exc:
        validate_identity(h)
    assert exc.value.details == {"field": "-".join(p.capitalize() for p in missing.split("-"))}
