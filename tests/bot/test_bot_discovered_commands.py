"""Telegram handles real drop-in command files according to declared policies."""

import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.io import command_plugins
from phishreport.logic import LogicManager

MODULE = "phishreport.io.command_plugins.zz_bot_extension_probe"
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def update_for(text, message_id=100):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=123, type="private"),
        effective_user=SimpleNamespace(id=42), callback_query=None,
        effective_message=SimpleNamespace(
            text=text, message_id=message_id,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message_id + 1000)),
        ),
    )


@pytest.fixture
def plugin_file(tmp_path, monkeypatch):
    monkeypatch.setattr(command_plugins, "__path__", [*command_plugins.__path__, str(tmp_path)])

    def install(body, *, policy="CommandPolicy()", factory_body="return ExtensionCommand()"):
        source = (
            "from phishreport.io.commands import Command, CommandPolicy, CommandReply\n"
            "from phishreport.io.check_command import CheckCommand, CheckOutcome\n"
            "FAILURE = ValueError('PRIVATE_FACTORY')\n"
            "class ExtensionCommand(Command):\n"
            "    name = 'extension_probe'\n"
            "    help_text = 'Temporary bot command'\n"
            f"    policy = {policy}\n"
            "    def execute(self, request):\n"
            + "\n".join("        " + line for line in body.splitlines())
            + "\ndef create_command(capabilities):\n"
            + "\n".join("    " + line for line in factory_body.splitlines()) + "\n"
        )
        (tmp_path / "zz_bot_extension_probe.py").write_text(source, encoding="utf-8")
        importlib.invalidate_caches()

    yield install
    sys.modules.pop(MODULE, None)
    attribute = MODULE.rsplit(".", 1)[-1]
    if hasattr(command_plugins, attribute):
        delattr(command_plugins, attribute)
    importlib.invalidate_caches()


@pytest.fixture
def extension_bot():
    ai = Mock(**{"assess.return_value": FINDINGS})
    data = Mock(**{"load.return_value": []})
    builder = Mock(wraps=ChatRecordBuilder())
    service = AssessmentService(ai, LogicManager())
    manager = TelegramIOManager(data, assessment=service, record_builder=builder)
    return manager, ai, data, builder


def test_drop_in_reply_and_help_work_without_assessment_lock_or_cache_capacity(
    plugin_file, extension_bot,
):
    plugin_file("return CommandReply('Echo: ' + request.text, 'text')")
    manager, ai, data, builder = extension_bot
    manager._assessment = None
    manager._session_limit = 0
    update = update_for(" /extension_probe   Mixed CASE ")
    help_update = update_for("/help", 101)

    async def scenario():
        manager._message_lock = asyncio.Lock()
        await manager._message_lock.acquire()
        try:
            await asyncio.wait_for(manager.assess_message(update, None), 1)
            await asyncio.wait_for(manager.assess_message(help_update, None), 1)
        finally:
            manager._message_lock.release()

    asyncio.run(scenario())

    update.effective_message.reply_text.assert_awaited_once_with("Echo: Mixed CASE ")
    assert "/extension_probe: Temporary bot command" in (
        help_update.effective_message.reply_text.await_args.args[0]
    )
    assert not manager._sessions
    ai.assess.assert_not_called()
    data.save.assert_not_called()
    data.load.assert_not_called()
    builder.build.assert_not_called()


def test_ordinary_assessment_shaped_reply_does_not_create_session(plugin_file, extension_bot):
    plugin_file("return CommandReply('Ordinary assessment-shaped reply', 'assessment')")
    manager, ai, data, builder = extension_bot
    update = update_for("/extension_probe")

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_awaited_once_with("Ordinary assessment-shaped reply")
    assert not manager._sessions
    ai.assess.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("execution", ["reply", "assessment"])
@pytest.mark.parametrize("error_type", ["OSError", "ValueError", "RuntimeError"])
@pytest.mark.parametrize("failure,expected", [
    ("command", "Sorry, the command failed. Please try again."),
    ("history", "Could not read local history. Please try again."),
])
def test_custom_command_expected_failures_use_policy_not_type(
    plugin_file, extension_bot, execution, error_type, failure, expected,
):
    plugin_file(
        f"raise {error_type}('PRIVATE_ERROR')",
        policy=f"CommandPolicy(execution='{execution}', failure='{failure}')",
    )
    manager, ai, data, builder = extension_bot
    update = update_for("/extension_probe")

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_awaited_once_with(expected)
    assert not manager._sessions
    ai.assess.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("execution", ["reply", "assessment"])
@pytest.mark.parametrize("error_type", ["OSError", "ValueError", "RuntimeError"])
def test_custom_assessment_failures_keep_assessment_presentation(
    plugin_file, extension_bot, execution, error_type,
):
    plugin_file(
        f"raise {error_type}('Assessment unavailable')",
        policy=f"CommandPolicy(execution='{execution}', failure='assessment')",
    )
    manager, ai, data, builder = extension_bot
    manager._error_translator = Mock(
        **{"translate.return_value": "Assessment temporarily unavailable"}
    )
    update = update_for("/extension_probe")

    asyncio.run(manager.assess_message(update, None))

    text = update.effective_message.reply_text.await_args.args[0]
    if error_type == "RuntimeError":
        manager._error_translator.translate.assert_called_once()
        assert text == "Assessment temporarily unavailable"
    elif error_type == "ValueError":
        assert text == "Sorry, the check failed: Assessment unavailable"
    else:
        assert text == "Sorry, the check failed. Please try again."
    assert not manager._sessions


def test_custom_assessment_keeps_findings_dedup_and_high_rescore(plugin_file, extension_bot):
    plugin_file(
        "return self.check.execute(request)",
        policy="CommandPolicy(execution='assessment', failure='assessment')",
        factory_body=(
            "command = ExtensionCommand()\n"
            "command.check = CheckCommand(\n"
            "    capabilities.prepare_record, capabilities.assess_record)\n"
            "return command"
        ),
    )
    manager, ai, data, builder = extension_bot
    update = update_for("/extension_probe Verify PASSWORD https://example.test/login ")

    async def scenario():
        await manager.assess_message(update, None)
        await manager.assess_message(update, None)
        session, = manager._sessions.values()
        assert session.record["message"] == "Verify PASSWORD https://example.test/login "
        assert session.findings == FINDINGS
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
        assert session.result["score"] == 80 and session.result["priority"] == "HIGH"

    asyncio.run(scenario())

    ai.assess.assert_called_once()
    builder.build.assert_called_once()
    update.effective_message.reply_text.assert_awaited_once()
    data.save.assert_not_called()


@pytest.mark.parametrize("body,error_type", [
    ("return CommandReply('Missing outcome', 'assessment')", KeyError),
    ("request.session['check_outcome'] = object()\n"
     "return CommandReply('Wrong outcome', 'assessment')", TypeError),
    ("request.session['check_outcome'] = CheckOutcome({}, {}, None)\n"
     "return CommandReply('Missing findings', 'assessment')", TypeError),
])
def test_bad_assessment_outcomes_surface_as_programming_errors(
    plugin_file, extension_bot, body, error_type,
):
    plugin_file(body, policy="CommandPolicy(execution='assessment')")
    manager, ai, data, builder = extension_bot

    with pytest.raises(error_type):
        asyncio.run(manager.assess_message(update_for("/extension_probe"), None))

    assert not manager._sessions
    data.save.assert_not_called()


@pytest.mark.parametrize("text", [" Plain CASE  ", "/unknown Plain CASE  "])
def test_free_unknown_assessment_io_errors_surface_without_command_translation(extension_bot, text):
    manager, ai, data, builder = extension_bot
    error = OSError("Assessment I/O failure")
    ai.assess.side_effect = error
    update = update_for(text)

    with pytest.raises(OSError) as caught:
        asyncio.run(manager.assess_message(update, None))

    assert caught.value is error
    builder.build.assert_called_once_with(text)
    update.effective_message.reply_text.assert_not_awaited()


def test_factory_error_is_not_translated_as_service_failure(plugin_file, extension_bot):
    plugin_file("return CommandReply('Unused', 'text')", factory_body="raise FAILURE")
    module = importlib.import_module(MODULE)
    manager, ai, data, builder = extension_bot
    update = update_for("/help")

    with pytest.raises(ValueError) as caught:
        asyncio.run(manager.assess_message(update, None))

    assert caught.value is module.FAILURE
    update.effective_message.reply_text.assert_not_awaited()
    ai.assess.assert_not_called()


@pytest.mark.parametrize("error_type", ["KeyError", "TypeError"])
def test_custom_command_programming_errors_surface(plugin_file, extension_bot, error_type):
    plugin_file(f"raise {error_type}('Programming error')")
    manager, ai, data, builder = extension_bot
    expected = KeyError if error_type == "KeyError" else TypeError

    with pytest.raises(expected):
        asyncio.run(manager.assess_message(update_for("/extension_probe"), None))

    assert not manager._sessions


@pytest.mark.parametrize("execution", ["reply", "assessment"])
def test_reply_delivery_errors_are_not_translated_as_command_failures(
    plugin_file, extension_bot, execution,
):
    plugin_file(
        "return CommandReply('Reply text', 'usage')",
        policy=f"CommandPolicy(execution='{execution}')",
    )
    manager, ai, data, builder = extension_bot
    update = update_for("/extension_probe")
    error = ValueError("Delivery programming error")
    update.effective_message.reply_text.side_effect = error

    with pytest.raises(ValueError) as caught:
        asyncio.run(manager.assess_message(update, None))

    assert caught.value is error
    update.effective_message.reply_text.assert_awaited_once_with("Reply text")
