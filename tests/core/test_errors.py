"""Public failure messages stay safe while causes remain available for diagnosis."""

import pytest

from phishreport.errors import (
    AIUnavailable,
    AssessmentError,
    FeedbackRejected,
    InvalidInput,
    StorageFailure,
)

ERROR_TYPES = (
    AssessmentError,
    AIUnavailable,
    InvalidInput,
    StorageFailure,
    FeedbackRejected,
)


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_default_message_is_nonempty_and_used_by_exception_display(error_type):
    error = error_type()

    assert isinstance(error.user_message, str)
    assert error.user_message.strip()
    assert str(error) == error.user_message
    assert error.args == (error.user_message,)
    assert error.user_message in repr(error)


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_all_errors_can_be_handled_through_assessment_error(error_type):
    with pytest.raises(AssessmentError) as caught:
        raise error_type()

    assert type(caught.value) is error_type


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_constructor_rejects_raw_diagnostic_message(error_type):
    with pytest.raises(TypeError):
        error_type("provider token=secret; private report path")


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_chained_cause_is_available_without_entering_safe_display(error_type):
    diagnostic = "provider token=secret; private report path"
    cause = RuntimeError(diagnostic)

    with pytest.raises(AssessmentError) as caught:
        raise error_type() from cause

    error = caught.value
    assert error.__cause__ is cause
    assert diagnostic not in str(error)
    assert diagnostic not in repr(error)
    assert diagnostic not in error.user_message
