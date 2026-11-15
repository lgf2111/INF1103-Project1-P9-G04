"""Translate only trusted error metadata into user-facing guidance."""

import pytest

from phishreport.ai import errors as ai_errors
from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason
from phishreport.ai.errors import AIErrorTranslator
from phishreport.errors import (
    AIUnavailable,
    AssessmentError,
    FeedbackRejected,
    InvalidInput,
    StorageFailure,
)

GENERIC = "The check failed: the AI could not complete the assessment. Please try again."
REACH = (
    "The check failed: could not reach the AI service. "
    "Check your internet connection and try again."
)
UNAVAILABLE = "The check failed: the AI service is temporarily unavailable. Try again shortly."
BUSY = "The check failed: the AI service is busy (rate limited). Try again shortly."


@pytest.mark.parametrize("reason,status,expected", [
    (ProviderFailureReason.TIMEOUT, None, REACH),
    (ProviderFailureReason.TRANSPORT, None, REACH),
    (ProviderFailureReason.HTTP, 500, UNAVAILABLE),
    (ProviderFailureReason.HTTP, 599, UNAVAILABLE),
    (ProviderFailureReason.HTTP, 429, BUSY),
    (ProviderFailureReason.HTTP, 499, GENERIC),
    (ProviderFailureReason.HTTP, 400, GENERIC),
    (ProviderFailureReason.CONFIGURATION, None, GENERIC),
    (ProviderFailureReason.INVALID_RESPONSE, None, GENERIC),
])
def test_provider_metadata_selects_safe_guidance(reason, status, expected):
    error = ProviderFailure(reason, status_code=status)
    assert AIErrorTranslator().translate(error) == expected


@pytest.mark.parametrize("text", ["HTTP 429", "HTTP 500", "timed out", "could not complete"])
def test_arbitrary_text_cannot_impersonate_provider_metadata(text):
    assert AIErrorTranslator().translate(RuntimeError(text)) == GENERIC


class HostileError(RuntimeError):
    def __str__(self):
        raise AssertionError("Exception text must not be inspected")

    def __repr__(self):
        raise AssertionError("Exception representation must not be inspected")


def test_unknown_error_is_never_stringified():
    assert AIErrorTranslator().translate(HostileError()) == GENERIC


@pytest.mark.parametrize("error_type", [
    AssessmentError, AIUnavailable, InvalidInput, StorageFailure, FeedbackRejected,
])
def test_domain_error_uses_its_safe_user_message(error_type):
    error = error_type()
    error.__cause__ = HostileError()
    assert AIErrorTranslator().translate(error) == error.user_message


def test_ai_unavailable_preserves_immediate_typed_provider_guidance():
    error = AIUnavailable()
    error.__cause__ = ProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    assert AIErrorTranslator().translate(error) == BUSY


def test_only_ai_unavailable_unwraps_provider_metadata():
    error = InvalidInput()
    error.__cause__ = ProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    assert AIErrorTranslator().translate(error) == error.user_message


def test_ai_unavailable_does_not_traverse_cause_chains():
    error = AIUnavailable()
    intermediate = RuntimeError("HTTP 429")
    intermediate.__cause__ = ProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    error.__cause__ = intermediate
    assert AIErrorTranslator().translate(error) == error.user_message
    error.__cause__ = error
    assert AIErrorTranslator().translate(error) == error.user_message

class HostileProviderFailure(ProviderFailure):
    def __str__(self):
        raise AssertionError("Provider text must not be inspected")

    def __repr__(self):
        raise AssertionError("Provider representation must not be inspected")


def test_typed_provider_guidance_never_stringifies_error():
    error = HostileProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    assert AIErrorTranslator().translate(error) == BUSY


@pytest.mark.parametrize("reason,status,expected", [
    (ProviderFailureReason.TIMEOUT, None, REACH),
    (ProviderFailureReason.TRANSPORT, None, REACH),
    (ProviderFailureReason.HTTP, 500, UNAVAILABLE),
    (ProviderFailureReason.HTTP, 599, UNAVAILABLE),
    (ProviderFailureReason.HTTP, 429, BUSY),
    (ProviderFailureReason.HTTP, 400, GENERIC),
    (ProviderFailureReason.CONFIGURATION, None, GENERIC),
    (ProviderFailureReason.INVALID_RESPONSE, None, GENERIC),
])
def test_provider_failure_mapping_preserves_typed_guidance(reason, status, expected):
    provider = ProviderFailure(reason, status_code=status)

    mapped = ai_errors.provider_failure_to_assessment_error(provider)

    assert isinstance(mapped, AIUnavailable)
    assert mapped.__cause__ is provider
    assert AIErrorTranslator().translate(mapped) == expected


def test_provider_failure_mapping_keeps_diagnostics_out_of_safe_display():
    provider = HostileProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    provider.__cause__ = RuntimeError("secret-token raw provider response")

    mapped = ai_errors.provider_failure_to_assessment_error(provider)

    assert mapped.__cause__ is provider
    assert mapped.user_message == AIUnavailable.user_message
    assert str(mapped) == AIUnavailable.user_message
    assert mapped.args == (AIUnavailable.user_message,)
    assert repr(mapped) == repr(AIUnavailable())
    assert AIErrorTranslator().translate(mapped) == BUSY


def test_provider_failure_mapping_returns_a_fresh_wrapper_each_time():
    provider = ProviderFailure(ProviderFailureReason.TIMEOUT)

    first = ai_errors.provider_failure_to_assessment_error(provider)
    second = ai_errors.provider_failure_to_assessment_error(provider)

    assert first is not second
    assert first.__cause__ is second.__cause__ is provider


@pytest.mark.parametrize("error", [
    HostileError(), RuntimeError("secret"), ValueError("secret"), None,
])
def test_provider_failure_mapping_rejects_unknown_values_without_formatting(error):
    with pytest.raises(TypeError) as caught:
        ai_errors.provider_failure_to_assessment_error(error)

    assert str(caught.value) == "error must be a ProviderFailure"
