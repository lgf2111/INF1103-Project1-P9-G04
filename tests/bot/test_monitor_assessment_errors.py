"""Typed assessment failures preserve mailbox progress and completed alerts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason
from phishreport.assessment import AssessmentService
from phishreport.bot.gmail import AccountStore, LinkedAccount
from phishreport.bot.monitor import FLAGGED, EmailMonitor
from phishreport.errors import AIUnavailable, AssessmentError, InvalidInput, StorageFailure
from phishreport.logic import LogicManager

RAW = b"From: bank@example.test\r\nSubject: Verify\r\n\r\nVerify your password."
SECRET = "private-token-email-body"


def monitor_for(tmp_path):
    store = AccountStore(tmp_path / "gmail.json")
    store.save(LinkedAccount(1, "a@gmail.com", "password", 5))
    provider = Mock()
    provider.assess.return_value = {
        "suspicious": True, "credential_request": True, "insufficient_context": False,
    }
    service = AssessmentService(provider, LogicManager())
    data = Mock()
    bot = SimpleNamespace(send_message=AsyncMock())
    mailbox = SimpleNamespace(new_since=lambda uid: [(9, RAW)])
    monitor = EmailMonitor(
        bot, store, service, data, asyncio.Lock(),
        mailbox_factory=lambda address, password: mailbox, feedback_service=object(),
    )
    return monitor, store, bot, data, provider


@pytest.mark.parametrize("failure", [
    AIUnavailable(), AssessmentError(),
    ProviderFailure(ProviderFailureReason.HTTP, status_code=429),
    ProviderFailure(ProviderFailureReason.HTTP, status_code=401),
    ProviderFailure(ProviderFailureReason.CONFIGURATION),
    ProviderFailure(ProviderFailureReason.INVALID_RESPONSE),
])
def test_typed_assessment_failure_keeps_uid_without_rechecking(tmp_path, capsys, failure):
    monitor, store, bot, data, _ = monitor_for(tmp_path)
    error = AIUnavailable() if isinstance(failure, ProviderFailure) else failure
    error.__cause__ = failure if error is not failure else RuntimeError(SECRET)
    assess = Mock(side_effect=error)
    monitor._assessment = SimpleNamespace(assess=assess)

    asyncio.run(monitor.poll_once())

    assert store.get(1).last_uid == 5
    assess.assert_called_once()
    data.save.assert_not_called()
    bot.send_message.assert_not_awaited()
    output = capsys.readouterr().out
    assert "will retry" in output
    assert SECRET not in output


def test_invalid_input_skips_and_advances_uid_safely(tmp_path, capsys):
    monitor, store, bot, data, _ = monitor_for(tmp_path)
    error = InvalidInput()
    error.__cause__ = ValueError(SECRET)
    monitor._assessment = SimpleNamespace(assess=Mock(side_effect=error))

    asyncio.run(monitor.poll_once())

    assert store.get(1).last_uid == 9
    data.save.assert_not_called()
    bot.send_message.assert_not_awaited()
    output = capsys.readouterr().out
    assert "Skipped an email the AI could not assess." in output
    assert SECRET not in output


def test_typed_storage_failure_still_alerts_without_feedback_or_second_ai_call(tmp_path, capsys):
    monitor, store, bot, data, provider = monitor_for(tmp_path)
    error = StorageFailure()
    error.__cause__ = OSError(SECRET)
    data.save.side_effect = error

    outcome = asyncio.run(monitor._assess_email(store.get(1), RAW))

    assert outcome == FLAGGED
    provider.assess.assert_called_once()
    data.save.assert_called_once()
    bot.send_message.assert_awaited_once()
    assert "MEDIUM risk" in bot.send_message.call_args.kwargs["text"]
    assert "<b>Score:</b> 60/100" in bot.send_message.call_args.kwargs["text"]
    assert "reply_markup" not in bot.send_message.call_args.kwargs
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("error_type", [TypeError, KeyError, RuntimeError, ValueError])
def test_programming_errors_escape_assessment_boundary(tmp_path, error_type):
    monitor, store, _, _, _ = monitor_for(tmp_path)
    monitor._assessment = SimpleNamespace(assess=Mock(side_effect=error_type(SECRET)))

    with pytest.raises(error_type):
        asyncio.run(monitor._assess_email(store.get(1), RAW))
