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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler

from phishreport.assessment import AssessmentSnapshot
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.handlers import CHECK_CONNECTION, TelegramIOManager
from phishreport.bot.main import main
from phishreport.bot.messages import ChatRecordBuilder, ResultFormatter
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage

ALLOWED_CHAT_ID = 12345


def test_constructor_tracking_starts_empty_and_isolated_per_manager():
    first = TelegramIOManager(Mock(spec=DataManager))
    second = TelegramIOManager(Mock(spec=DataManager))

    assert first._sessions == second._sessions == {}
    assert first._source_sessions == second._source_sessions == {}
    assert first._session_limit == second._session_limit == 1000
    assert first._sessions is not second._sessions
    assert first._source_sessions is not second._source_sessions
    assert first.save_lock is first._save_lock
    assert isinstance(first.save_lock, asyncio.Lock)
    assert first.save_lock is not second.save_lock
    assert not first.save_lock.locked()


def test_constructor_tracking_maps_keep_distinct_source_identities():
    manager = TelegramIOManager(Mock(spec=DataManager))
    sibling = TelegramIOManager(Mock(spec=DataManager))
    snapshot = AssessmentSnapshot(findings={}, result={"score": 0})
    identities = [(10, 20, 30), (10, 20, 31), (11, 20, 30), (10, 21, 30)]
    sessions = []
    # Populate the caches directly; handler routing is a later checkpoint.
    for chat_id, user_id, message_id in identities:
        session = ExposureSession(
            {"message": "Identical text"}, snapshot,
            chat_id=chat_id, user_id=user_id, message_id=message_id,
        )
        sessions.append(session)
        manager._sessions[session.token] = session
        manager._source_sessions[(chat_id, user_id, message_id)] = session.token

    assert len(manager._sessions) == len(manager._source_sessions) == 4
    for identity, session in zip(identities, sessions, strict=True):
        assert manager._sessions[manager._source_sessions[identity]] is session
    assert sibling._sessions == sibling._source_sessions == {}


@pytest.mark.parametrize("with_assessment", [False, True])
def test_constructor_tracking_retains_collaborators_without_calling_them(with_assessment):
    storage = Mock(spec=DataManager)
    assessment = Mock() if with_assessment else None
    builder = Mock(spec=ChatRecordBuilder)
    formatter = Mock(spec=ResultFormatter)
    translator = Mock()

    manager = TelegramIOManager(
        storage, ALLOWED_CHAT_ID, assessment, builder, formatter, translator
    )

    assert manager._data_manager is storage
    assert manager._allowed_chat_id == ALLOWED_CHAT_ID
    assert manager._assessment is assessment
    assert manager._record_builder is builder
    assert manager._formatter is formatter
    assert manager._error_translator is translator
    assert manager._sessions == manager._source_sessions == {}
    for collaborator in (storage, assessment, builder, formatter, translator):
        if collaborator is not None:
            assert collaborator.mock_calls == []


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
    assert reply.args[0].startswith("Welcome to PhishReport.")
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


def test_without_allowed_chat_any_private_chat_is_served_but_not_groups():
    data_manager = Mock(spec=DataManager)
    manager = TelegramIOManager(data_manager)

    private = fake_update(chat_id=67890)
    asyncio.run(manager.start(private, None))
    private.effective_message.reply_text.assert_awaited_once()

    group = fake_update(chat_id=67890, chat_type="group")
    asyncio.run(manager.start(group, None))
    group.effective_message.reply_text.assert_not_called()


@pytest.mark.parametrize("backend", [None, "json", "sqlite"], ids=["default", "json", "sqlite"])
def test_launcher_selects_storage_without_changing_other_history(tmp_path, monkeypatch, backend):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "")
    monkeypatch.delenv("PHISHREPORT_STORAGE", raising=False)
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr("phishreport.bot.main.AppLogging.setup", lambda: True)
    if backend is not None:
        monkeypatch.setenv("PHISHREPORT_STORAGE", backend)

    def report(message):
        return {
            "schema_version": 2,
            "channel": "chat",
            "message": message,
            "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
        }

    json_storage = JsonReportStorage(tmp_path / "history.json")
    json_storage.write_records([report("JSON history")])
    original_json = (tmp_path / "history.json").read_bytes()
    if backend == "sqlite":
        selected = SqliteReportStorage(tmp_path / "history.sqlite3")
        existing = report("SQLite history")
        selected.write_records([existing])
    else:
        selected = json_storage
        existing = report("JSON history")

    with patch.object(Application, "run_polling", autospec=True) as polling:
        assert main() == 0
    (application,) = polling.call_args.args
    check = next(
        handler for handler in application.handlers[0]
        if isinstance(handler, CallbackQueryHandler)
    )
    manager = check.callback.__self__
    assert manager._data_manager.load(strict=True) == [existing]
    added = report("New report")
    manager._data_manager.save(added)
    assert selected.read_records() == [existing, added]
    if backend == "sqlite":
        assert (tmp_path / "history.json").read_bytes() == original_json
    else:
        assert not (tmp_path / "history.sqlite3").exists()


def test_launcher_accepts_blank_allowed_chat_and_rejects_bad_values(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "")
    with patch.object(Application, "run_polling", autospec=True) as polling:
        assert main() == 0
    polling.assert_called_once()

    for bad in ("abc", "-5", "0"):
        monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", bad)
        assert main() == 1


def test_launcher_registers_welcome_and_button_handlers_for_polling(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", str(ALLOWED_CHAT_ID))

    with patch.object(Application, "run_polling", autospec=True) as polling:
        assert main() == 0

    (app,) = polling.call_args.args
    polling.assert_called_once_with(app, allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
    start, link, checkmail, unlink, check, text = app.handlers[0]
    assert isinstance(start, CommandHandler)
    assert start.commands == {"start"}
    assert link.commands == {"linkgmail"}
    assert checkmail.commands == {"checkmail"}
    assert unlink.commands == {"unlinkgmail"}
    assert isinstance(check, CallbackQueryHandler)
    assert check.pattern.match(CHECK_CONNECTION)
    assert not check.pattern.match(CHECK_CONNECTION + "\n")
    assert isinstance(text, MessageHandler)


def test_normal_launcher_imports_without_pytest_path_or_credentials():
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "phishreport.bot"],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "Set TELEGRAM_BOT_TOKEN to the existing bot token."
