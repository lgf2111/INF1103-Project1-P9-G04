"""Typed assessment failures stop Telegram assessment side effects safely."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason
from phishreport.bot import handlers
from phishreport.bot.handlers import TelegramIOManager
from phishreport.errors import (
    AIUnavailable,
    AssessmentError,
    FeedbackRejected,
    InvalidInput,
    StorageFailure,
)
from phishreport.io.commands import Command, CommandPolicy


@pytest.fixture
def parts():
    data, assessment = Mock(), Mock()
    manager = TelegramIOManager(data, assessment=assessment)
    message = SimpleNamespace(message_id=100, text="Check me", reply_text=AsyncMock())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=123, type="private"),
        effective_user=SimpleNamespace(id=42), effective_message=message,
        callback_query=None,
    )
    return manager, assessment, data, update


def invoke(parts, text):
    manager, _, _, update = parts
    update.effective_message.text = text
    asyncio.run(manager.assess_message(update, None))


def assert_stopped(parts, expected):
    manager, assessment, data, update = parts
    update.effective_message.reply_text.assert_awaited_once_with(expected)
    assert manager._sessions == {} and manager._source_sessions == {}
    data.save.assert_not_called()
    assessment.rescore.assert_not_called()


@pytest.mark.parametrize("text", ["Check me", "/check Check me"])
@pytest.mark.parametrize(
    "error_type", [AssessmentError, AIUnavailable, InvalidInput, StorageFailure, FeedbackRejected],
)
def test_typed_assessment_failure_is_safe_and_stops_followup(parts, text, error_type):
    error = error_type()
    error.__cause__ = RuntimeError("PRIVATE credentials")
    parts[1].assess_with_findings.side_effect = error

    invoke(parts, text)

    assert_stopped(parts, error.user_message)
    parts[1].assess_with_findings.assert_called_once()


@pytest.mark.parametrize("text", ["Check me", "/check Check me"])
def test_typed_ai_failure_uses_provider_guidance(parts, text):
    error = AIUnavailable()
    error.__cause__ = ProviderFailure(ProviderFailureReason.TIMEOUT)
    error.__cause__.__cause__ = RuntimeError("PRIVATE token")
    parts[1].assess_with_findings.side_effect = error

    invoke(parts, text)

    assert_stopped(parts, "The check failed: could not reach the AI service. "
                   "Check your internet connection and try again.")


def test_free_text_record_failure_never_calls_assessment(parts):
    parts[0]._record_builder = Mock(build=Mock(side_effect=InvalidInput()))

    invoke(parts, "Check me")

    assert_stopped(parts, "Invalid input. Please revise it and try again.")
    parts[1].assess_with_findings.assert_not_called()


@pytest.mark.parametrize("execution", ["reply", "assessment"])
@pytest.mark.parametrize("failure,expected", [
    ("history", "Could not read local history. Please try again."),
    ("command", "Sorry, the command failed. Please try again."),
    ("assessment", "Could not access local report history. Please try again."),
])
def test_command_failure_policy_precedes_typed_message(
    parts, monkeypatch, execution, failure, expected,
):
    class FailingCommand(Command):
        name = "failure"
        help_text = "Fail offline"
        policy = CommandPolicy(execution=execution, failure=failure)

        def execute(self, request):
            raise StorageFailure() from OSError("PRIVATE path")

    monkeypatch.setattr(handlers, "discover_commands", lambda capabilities: [FailingCommand()])

    invoke(parts, "/failure")

    assert_stopped(parts, expected)
    parts[1].assess_with_findings.assert_not_called()


@pytest.mark.parametrize("error_type", [TypeError, KeyError])
@pytest.mark.parametrize("stage", ["record", "direct", "check"])
def test_programming_errors_propagate(parts, error_type, stage):
    error = error_type("programmer bug")
    if stage == "record":
        parts[0]._record_builder = Mock(build=Mock(side_effect=error))
    else:
        parts[1].assess_with_findings.side_effect = error

    with pytest.raises(error_type, match="programmer bug"):
        invoke(parts, "/check Check me" if stage == "check" else "Check me")

    parts[3].effective_message.reply_text.assert_not_awaited()
    assert parts[0]._sessions == {}
    parts[2].save.assert_not_called()


@pytest.mark.parametrize("text", ["Check me", "/check Check me"])
@pytest.mark.parametrize("error,expected", [
    (ValueError("legacy validation"), "Sorry, the check failed: legacy validation"),
    (RuntimeError("PRIVATE token"),
     "The check failed: the AI could not complete the assessment. Please try again."),
])
def test_legacy_assessment_failure_behavior_is_preserved(parts, text, error, expected):
    parts[1].assess_with_findings.side_effect = error

    invoke(parts, text)

    assert_stopped(parts, expected)
