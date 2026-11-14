"""Contracts for safe, structured provider failures without live AI."""

import pytest

from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        (ProviderFailureReason.CONFIGURATION, "AI provider configuration is invalid."),
        (ProviderFailureReason.TIMEOUT, "The AI request timed out."),
        (ProviderFailureReason.TRANSPORT, "Could not complete the AI request."),
        (ProviderFailureReason.INVALID_RESPONSE, "AI provider returned an invalid response."),
    ],
)
def test_non_http_failures_have_safe_messages(reason, message):
    error = ProviderFailure(reason)

    assert isinstance(error, RuntimeError)
    assert error.reason is reason
    assert error.status_code is None
    assert str(error) == message
    assert error.args == (message,)


@pytest.mark.parametrize("status_code", [100, 429, 599])
def test_http_failure_preserves_valid_status(status_code):
    error = ProviderFailure(ProviderFailureReason.HTTP, status_code=status_code)

    assert error.reason is ProviderFailureReason.HTTP
    assert error.status_code == status_code
    assert str(error) == f"AI provider returned HTTP {status_code}."


@pytest.mark.parametrize("reason", [None, "timeout", "private-token-123", 1])
def test_invalid_reason_is_rejected_without_echoing_input(reason):
    with pytest.raises(TypeError) as caught:
        ProviderFailure(reason)

    assert str(caught.value) == "reason must be a ProviderFailureReason."


@pytest.mark.parametrize("status_code", [None, 99, 600])
def test_http_requires_status_in_range(status_code):
    with pytest.raises(ValueError):
        ProviderFailure(ProviderFailureReason.HTTP, status_code=status_code)


@pytest.mark.parametrize("reason", [ProviderFailureReason.HTTP, ProviderFailureReason.TIMEOUT])
@pytest.mark.parametrize("status_code", [True, 429.0, "private-token-123"])
def test_non_integer_status_is_rejected_safely(reason, status_code):
    with pytest.raises(TypeError) as caught:
        ProviderFailure(reason, status_code=status_code)

    assert str(caught.value) == "status_code must be an integer."


@pytest.mark.parametrize(
    "reason",
    [
        ProviderFailureReason.CONFIGURATION,
        ProviderFailureReason.TIMEOUT,
        ProviderFailureReason.TRANSPORT,
        ProviderFailureReason.INVALID_RESPONSE,
    ],
)
def test_non_http_failure_rejects_status(reason):
    with pytest.raises(ValueError):
        ProviderFailure(reason, status_code=429)


def test_safe_representation_keeps_chained_cause_private():
    cause = ValueError("private-token-123 response body")
    with pytest.raises(RuntimeError) as caught:
        raise ProviderFailure(ProviderFailureReason.TRANSPORT) from cause

    error = caught.value
    assert error.__cause__ is cause
    assert "private-token-123" not in str(error)
    assert "private-token-123" not in repr(error)
    assert error.args == ("Could not complete the AI request.",)
