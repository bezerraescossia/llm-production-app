import pytest

from ai_services.errors import ErrorCode, ServiceError
from ai_services.gateway.errors import (
    GatewayError,
    GenerationSettingError,
    ProviderCategory,
    ProviderError,
    UnknownTierError,
    error_for_failures,
)

C = ProviderCategory


def test_categories_are_the_documented_set() -> None:
    assert {c.value for c in ProviderCategory} == {
        "temporary",
        "rate_limited",
        "timeout",
        "unavailable",
        "auth",
        "context_too_large",
        "content_blocked",
        "invalid_request",
    }


def test_provider_error_carries_a_category_and_no_provider_text() -> None:
    err = ProviderError(C.RATE_LIMITED, retry_after_seconds=3.0)
    assert err.category is C.RATE_LIMITED and err.retry_after_seconds == 3.0
    assert str(err) == "rate_limited"  # the category only, never provider text


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.UPSTREAM_UNAVAILABLE, 503),
        (ErrorCode.UPSTREAM_TIMEOUT, 504),
        (ErrorCode.UPSTREAM_ERROR, 502),
        (ErrorCode.INPUT_TOO_LARGE, 422),
    ],
)
def test_gateway_error_is_a_service_error_with_status_and_generic_message(
    code: ErrorCode, status: int
) -> None:
    err = GatewayError(code, retry_after_seconds=5)
    assert isinstance(err, ServiceError)
    assert err.status_code == status and err.retry_after_seconds == 5
    assert err.message and "traceback" not in err.message.lower()


def test_gateway_error_refuses_non_upstream_codes() -> None:
    with pytest.raises(ValueError):
        GatewayError(ErrorCode.UNAUTHORIZED)


@pytest.mark.parametrize(
    ("seen", "expected"),
    [
        ([C.TIMEOUT, C.TIMEOUT], ErrorCode.UPSTREAM_TIMEOUT),
        ([C.AUTH], ErrorCode.UPSTREAM_ERROR),
        ([C.AUTH, C.INVALID_REQUEST], ErrorCode.UPSTREAM_ERROR),
        ([C.CONTEXT_TOO_LARGE, C.CONTEXT_TOO_LARGE], ErrorCode.INPUT_TOO_LARGE),
        ([C.TEMPORARY, C.TEMPORARY], ErrorCode.UPSTREAM_UNAVAILABLE),
        ([C.RATE_LIMITED], ErrorCode.UPSTREAM_UNAVAILABLE),
        ([C.UNAVAILABLE], ErrorCode.UPSTREAM_UNAVAILABLE),
        ([C.TIMEOUT, C.TEMPORARY], ErrorCode.UPSTREAM_UNAVAILABLE),
        ([C.AUTH, C.TEMPORARY], ErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
def test_final_error_is_chosen_from_the_failure_categories(
    seen: list[ProviderCategory], expected: ErrorCode
) -> None:
    assert error_for_failures(seen).code is expected


def test_unavailable_errors_carry_a_retry_hint() -> None:
    err = error_for_failures([C.TEMPORARY])
    assert err.code is ErrorCode.UPSTREAM_UNAVAILABLE and (err.retry_after_seconds or 0) > 0


def test_no_failures_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        error_for_failures([])


def test_programming_errors_name_what_is_wrong() -> None:
    assert "huge" in str(UnknownTierError("huge"))
    err = GenerationSettingError("max_output_tokens", requested=9000, ceiling=4096)
    assert "max_output_tokens" in str(err) and "4096" in str(err)
