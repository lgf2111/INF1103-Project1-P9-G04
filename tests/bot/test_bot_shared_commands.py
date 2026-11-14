"""Shared bot commands preserve the original free-text assessment boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.io.check_command import CheckCommand
from phishreport.io.commands import CommandRouter
from phishreport.io.help_command import HelpCommand
from phishreport.logic import LogicManager

FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def message_update(text, message_id=100):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=123, type="private"),
        effective_user=SimpleNamespace(id=42), callback_query=None,
        effective_message=SimpleNamespace(
            text=text, message_id=message_id,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message_id + 1000)),
        ),
    )


@pytest.fixture
def command_bot():
    ai = Mock(**{"assess.return_value": FINDINGS})
    data = Mock()
    builder = Mock(wraps=ChatRecordBuilder())
    service = AssessmentService(ai, LogicManager())
    manager = TelegramIOManager(data, assessment=service, record_builder=builder)
    return manager, ai, data, builder


@pytest.mark.parametrize("text", [
    "  Mixed CASE\nKeep  spaces  ", "/unknown Keep CASE  ", "/CHECK Content", "/checker Text",
])
def test_bot_non_commands_reach_original_builder_untouched(command_bot, monkeypatch, text):
    manager, ai, data, builder = command_bot
    execute = Mock(side_effect=AssertionError("Non-command executed"))
    monkeypatch.setattr(CheckCommand, "execute", execute)
    update = message_update(text)

    asyncio.run(manager.assess_message(update, None))

    builder.build.assert_called_once_with(text)
    execute.assert_not_called()
    ai.assess.assert_called_once()
    session, = manager._sessions.values()
    assert session.record["message"] == text
    assert session.findings == FINDINGS
    assert "Provisional assessment" in update.effective_message.reply_text.call_args.args[0]
    data.save.assert_not_called()


def test_bot_check_routes_once_and_retains_snapshot_for_exposure(command_bot, monkeypatch):
    manager, ai, data, builder = command_bot
    raw = "  /check   Verify PASSWORD https://example.test/path  "
    update = message_update(raw)
    routed, executed = [], []
    original_route, original_execute = CommandRouter.route, CheckCommand.execute

    def route(router, request):
        routed.append(request.text)
        return original_route(router, request)

    def execute(command, request):
        executed.append(request.text)
        return original_execute(command, request)

    monkeypatch.setattr(CommandRouter, "route", route)
    monkeypatch.setattr(CheckCommand, "execute", execute)

    async def flow():
        await manager.assess_message(update, None)
        await manager.assess_message(update, None)
        session, = manager._sessions.values()
        callback = SimpleNamespace(
            effective_chat=SimpleNamespace(id=123, type="private"),
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(message_id=session.reply_message_id),
            callback_query=SimpleNamespace(
                data=f"exposure:{session.token}:clicked", answer=AsyncMock(),
                edit_message_text=AsyncMock(),
            ),
        )
        await manager.exposure_callback(callback, None)
        assert session.result["score"] == 80
        assert session.result["priority"] == "HIGH"

    asyncio.run(flow())

    assert routed == [raw]
    assert executed == ["Verify PASSWORD https://example.test/path  "]
    builder.build.assert_called_once_with(executed[0])
    ai.assess.assert_called_once()
    update.effective_message.reply_text.assert_called_once()
    data.save.assert_not_called()


@pytest.mark.parametrize("available", [True, False])
def test_bot_help_uses_shared_help_without_assessment_or_history(
    command_bot, monkeypatch, available,
):
    manager, ai, data, builder = command_bot
    if not available:
        manager._assessment = None
    update = message_update(" /help ignored ")
    helped = []
    original = HelpCommand.execute

    def execute(command, request):
        helped.append(request.text)
        return original(command, request)

    monkeypatch.setattr(HelpCommand, "execute", execute)
    asyncio.run(manager.assess_message(update, None))

    assert helped == ["ignored "]
    assert "/help:" in update.effective_message.reply_text.call_args.args[0]
    builder.build.assert_not_called()
    ai.assess.assert_not_called()
    data.load.assert_not_called()
    data.save.assert_not_called()
    assert manager._sessions == {}


def test_bot_empty_check_returns_usage_without_assessment_or_session(command_bot):
    manager, ai, data, builder = command_bot
    update = message_update("/check \t ")

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_called_once_with("Usage: /check <text>")
    builder.build.assert_not_called()
    ai.assess.assert_not_called()
    data.save.assert_not_called()
    assert manager._sessions == {}


def test_bot_pending_feedback_keeps_slash_text_as_comment(command_bot, monkeypatch):
    manager, ai, data, builder = command_bot
    pending = {"assessment_id": "existing"}
    monkeypatch.setattr(manager, "_pending_feedback", Mock(return_value=pending))
    submit = AsyncMock()
    monkeypatch.setattr(manager, "_submit_feedback", submit)
    context = SimpleNamespace(user_data={})
    update = message_update("/check This is feedback")

    asyncio.run(manager.assess_message(update, context))

    submit.assert_awaited_once_with(update, context, pending, "/check This is feedback")
    builder.build.assert_not_called()
    ai.assess.assert_not_called()
