"""Exercise the Telegram welcome screen and check with offline updates."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from app_cli.data_core import DataManager, JsonReportStorage
from app_gui.main import main
from app_gui.telegram_io_manager import CHECK_CONNECTION, TelegramIOManager

ALLOWED_CHAT_ID = 12345


def fake_update(chat_id=ALLOWED_CHAT_ID, chat_type="private", *, has_chat=True):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type) if has_chat else None,
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        callback_query=SimpleNamespace(answer=AsyncMock()),
    )


def test_start_shows_one_connection_button():
    data_manager = Mock(spec=DataManager)
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID)
    update = fake_update()

    asyncio.run(manager.start(update, None))

    update.effective_message.reply_text.assert_awaited_once()
    reply = update.effective_message.reply_text.call_args
    assert reply.args == ("Welcome to PhishReport.",)
    ((button,),) = reply.kwargs["reply_markup"].inline_keyboard
    assert button.text == "Check connection"
    assert button.callback_data == CHECK_CONNECTION
    assert data_manager.mock_calls == []


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        (None, "Connection check passed."),
        (b"[]", "Connection check passed."),
        (b'[{"message": "private report text"}]', "Connection check passed."),
        (b"{private malformed text", "Could not read local history. Please try again."),
        (b'[{"score": "invalid"}]', "Could not read local history. Please try again."),
    ],
)
def test_connection_check_acks_then_reads_and_preserves_history(tmp_path, history, expected):
    path = tmp_path / "reports.json"
    if history is not None:
        path.write_bytes(history)
    data_manager = DataManager(JsonReportStorage(path))
    data_manager.load = Mock(wraps=data_manager.load)
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID)
    update = fake_update()
    sequence = Mock()
    sequence.attach_mock(update.callback_query.answer, "answer")
    sequence.attach_mock(data_manager.load, "load")
    sequence.attach_mock(update.effective_message.reply_text, "reply")

    asyncio.run(manager.check_connection(update, None))

    assert sequence.mock_calls == [call.answer(), call.load(strict=True), call.reply(expected)]
    update.callback_query.answer.assert_awaited_once_with()
    update.effective_message.reply_text.assert_awaited_once_with(expected)
    if history is None:
        assert list(tmp_path.iterdir()) == []
    else:
        assert path.read_bytes() == history
        assert list(tmp_path.iterdir()) == [path]


def test_connection_check_handles_io_error_without_disclosing_details():
    data_manager = Mock(spec=DataManager)
    data_manager.load.side_effect = PermissionError("sensitive path")
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID)
    update = fake_update()

    asyncio.run(manager.check_connection(update, None))

    update.callback_query.answer.assert_awaited_once_with()
    update.effective_message.reply_text.assert_awaited_once_with(
        "Could not read local history. Please try again."
    )
    assert data_manager.mock_calls == [call.load(strict=True)]


@pytest.mark.parametrize(
    "chat_settings", [{"chat_id": 67890}, {"chat_type": "group"}, {"has_chat": False}]
)
def test_unauthorized_updates_cannot_get_a_menu_or_read_history(chat_settings):
    data_manager = Mock(spec=DataManager)
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID)
    update = fake_update(**chat_settings)

    asyncio.run(manager.start(update, None))
    asyncio.run(manager.check_connection(update, None))

    update.effective_message.reply_text.assert_not_called()
    update.callback_query.answer.assert_not_called()
    assert data_manager.mock_calls == []


def test_launcher_registers_welcome_and_button_handlers_for_polling(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", str(ALLOWED_CHAT_ID))

    with patch.object(Application, "run_polling", autospec=True) as polling:
        assert main() == 0

    (app,) = polling.call_args.args
    polling.assert_called_once_with(app, allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
    start, check = app.handlers[0]
    assert isinstance(start, CommandHandler)
    assert start.commands == {"start"}
    assert isinstance(check, CallbackQueryHandler)
    assert check.pattern.match(CHECK_CONNECTION)
    assert not check.pattern.match(CHECK_CONNECTION + "\n")


def test_normal_launcher_imports_without_pytest_path_or_credentials():
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "app_gui.main"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "Set TELEGRAM_BOT_TOKEN to the existing bot token."
