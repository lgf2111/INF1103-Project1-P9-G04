"""Typed failures stop CLI side effects at the appropriate boundary."""

from unittest.mock import Mock

import pytest

from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason
from phishreport.cli.main import PhishReportApp
from phishreport.errors import (
    AIUnavailable,
    AssessmentError,
    FeedbackRejected,
    InvalidInput,
    StorageFailure,
)


@pytest.fixture
def app_parts():
    io, ai, logic, data, feedback = (Mock() for _ in range(5))
    io.build_record_from_message.return_value = {"channel": "chat", "message": "Check me"}
    ai.assess.return_value = {}
    logic.evaluate.return_value = {
        "score": 10, "priority": "LOW", "reasons": [], "checklist": [],
    }
    return PhishReportApp(io, ai, logic, data, feedback_service=feedback), io, ai, data, feedback


def invoke(app, command):
    if command:
        app.check_message(command_text="/check Check me")
    else:
        app.check_message({"channel": "chat", "message": "Check me"})


@pytest.mark.parametrize("command", [False, True])
@pytest.mark.parametrize(
    "error_type", [AssessmentError, AIUnavailable, InvalidInput, StorageFailure, FeedbackRejected],
)
def test_typed_assessment_failure_is_safe_and_stops_followup(app_parts, command, error_type):
    app, io, ai, data, feedback = app_parts
    error = error_type()
    error.__cause__ = RuntimeError("PRIVATE provider credentials")
    ai.assess.side_effect = error

    invoke(app, command)

    io.show_message.assert_called_once_with(error.user_message)
    data.save.assert_not_called()
    io.display_result.assert_not_called()
    io.collect_feedback.assert_not_called()
    feedback.submit.assert_not_called()


@pytest.mark.parametrize("command", [False, True])
def test_typed_ai_failure_uses_provider_guidance(app_parts, command):
    app, io, ai, data, feedback = app_parts
    error = AIUnavailable()
    error.__cause__ = ProviderFailure(ProviderFailureReason.TIMEOUT)
    error.__cause__.__cause__ = RuntimeError("PRIVATE token")
    ai.assess.side_effect = error

    invoke(app, command)

    io.show_message.assert_called_once_with(
        "The check failed: could not reach the AI service. "
        "Check your internet connection and try again."
    )
    data.save.assert_not_called()
    io.display_result.assert_not_called()
    feedback.submit.assert_not_called()


@pytest.mark.parametrize("command", [False, True])
def test_typed_save_failure_keeps_result_without_feedback(app_parts, command):
    app, io, ai, data, feedback = app_parts
    error = StorageFailure()
    error.__cause__ = OSError("PRIVATE disk path")
    data.save.side_effect = error

    invoke(app, command)

    io.show_message.assert_called_once_with(error.user_message)
    io.display_result.assert_called_once()
    assert io.display_result.call_args.args[0]["priority"] == "LOW"
    io.collect_feedback.assert_not_called()
    feedback.submit.assert_not_called()


def test_typed_history_command_failure_retains_history_policy(app_parts):
    app, io, ai, data, feedback = app_parts
    data.load.side_effect = StorageFailure()

    app.check_message(command_text="/status")

    io.show_message.assert_called_once_with(
        "Could not load local report history; existing file preserved."
    )
    ai.assess.assert_not_called()
    data.save.assert_not_called()
    io.display_result.assert_not_called()
    feedback.submit.assert_not_called()


@pytest.mark.parametrize("command", [False, True])
def test_programmer_type_error_still_propagates(app_parts, command):
    app, io, ai, data, feedback = app_parts
    ai.assess.side_effect = TypeError("programmer bug")

    with pytest.raises(TypeError, match="programmer bug"):
        invoke(app, command)

    io.show_message.assert_not_called()
    data.save.assert_not_called()
    io.display_result.assert_not_called()
    feedback.submit.assert_not_called()
