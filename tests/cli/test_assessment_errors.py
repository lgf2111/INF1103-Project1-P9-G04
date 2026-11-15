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


def test_typed_history_load_failure_is_safe_then_recovers(app_parts, monkeypatch):
    app, io, _, data, _ = app_parts
    error = StorageFailure()
    error.__cause__ = OSError("PRIVATE history path and credentials")
    data.load.side_effect = [error, []]
    log_failure = Mock()
    monkeypatch.setattr("phishreport.cli.main.AppLogging.log_failure", log_failure)

    assert app.load_reports() is None
    assert app.load_reports() == []

    assert data.load.call_count == 2
    assert all(call.kwargs == {"strict": True} for call in data.load.call_args_list)
    io.show_message.assert_called_once_with(
        "Could not load local report history; existing file preserved."
    )
    assert log_failure.call_count == 1


@pytest.mark.parametrize("operation", ["view_reports", "summarize_reports"])
def test_typed_history_failure_stops_history_consumers(app_parts, operation):
    app, io, _, data, _ = app_parts
    error = StorageFailure()
    error.__cause__ = OSError("PRIVATE history path")
    data.load.side_effect = error

    getattr(app, operation)()

    data.load.assert_called_once_with(strict=True)
    io.show_message.assert_called_once_with(
        "Could not load local report history; existing file preserved."
    )
    io.display_list.assert_not_called()
    io.collect_summary_filter.assert_not_called()
    io.display_summary.assert_not_called()
    app._logic_manager.build_filter.assert_not_called()
    app._logic_manager.summarize.assert_not_called()
    data.query.assert_not_called()


def test_history_load_programmer_type_error_propagates(app_parts):
    app, io, _, data, _ = app_parts
    data.load.side_effect = TypeError("history programmer bug")

    with pytest.raises(TypeError, match="history programmer bug"):
        app.load_reports()

    io.show_message.assert_not_called()


@pytest.mark.parametrize("error_type", [StorageFailure, FeedbackRejected, AssessmentError])
def test_typed_feedback_failure_preserves_assessment_then_recovers(app_parts, error_type, caplog):
    app, io, ai, data, feedback = app_parts
    error = error_type()
    error.__cause__ = OSError("PRIVATE feedback path and credentials")
    feedback.submit.side_effect = [error, None]
    io.collect_feedback.return_value = {"category": "incorrect"}
    caplog.set_level("WARNING", logger="phishreport.cli.main")

    invoke(app, False)

    io.show_message.assert_called_once_with(
        "Could not save your feedback. The assessment result is unchanged."
    )
    displayed = io.display_result.call_args.args[0]
    assert displayed == {
        "assessment_id": data.save.call_args.args[0]["assessment_id"],
        "score": 10, "priority": "LOW", "reasons": [], "checklist": [],
    }
    feedback.submit.assert_called_once_with(
        assessment_id=displayed["assessment_id"], assessment_result=displayed,
        category="incorrect",
    )
    ai.assess.assert_called_once()
    data.save.assert_called_once()
    io.display_result.assert_called_once()
    assert "Saving assessment feedback failed" in caplog.text
    assert "PRIVATE" not in caplog.text

    invoke(app, False)

    assert feedback.submit.call_count == 2
    assert io.show_message.call_count == 2
    assert io.show_message.call_args.args == (
        "Thank you. Your feedback was saved for review.",
    )


def test_skipped_feedback_never_submits(app_parts):
    app, io, _, _, feedback = app_parts
    io.collect_feedback.return_value = None

    app._collect_feedback({"assessment_id": "completed"})

    feedback.submit.assert_not_called()
    io.show_message.assert_not_called()


@pytest.mark.parametrize("error_type", [TypeError, KeyError])
def test_feedback_programmer_error_propagates(app_parts, error_type):
    app, io, _, _, feedback = app_parts
    io.collect_feedback.return_value = {"category": "incorrect"}
    feedback.submit.side_effect = error_type("feedback programmer bug")

    with pytest.raises(error_type, match="feedback programmer bug"):
        app._collect_feedback({"assessment_id": "completed"})

    feedback.submit.assert_called_once()
    io.show_message.assert_not_called()
