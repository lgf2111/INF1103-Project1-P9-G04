"""Bot status reads history off-loop and reports only owned live exposure sessions."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.bot import handlers as handlers_module
from phishreport.bot.handlers import TelegramIOManager
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.io.status_command import StatusCommand


def status_update(text="/status"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=123, type="private"),
        effective_user=SimpleNamespace(id=42), callback_query=None,
        effective_message=SimpleNamespace(text=text, message_id=100, reply_text=AsyncMock()),
    )


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("count", [0, 2])
def test_bot_status_reads_real_history_once_off_loop_without_assessment(
    monkeypatch, tmp_path, backend, count,
):
    storage = JsonReportStorage if backend == "json" else SqliteReportStorage
    data = DataManager(storage(tmp_path / "history"))
    for number in range(count):
        data.save({
            "schema_version": 2, "channel": "chat", "message": f"Saved {number}",
            "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
        })
    manager = TelegramIOManager(data, assessment=None)
    original_load = data.load
    main_thread = threading.get_ident()
    reads = []
    original_execute = StatusCommand.execute
    executed = []

    def load(*, strict):
        reads.append((strict, threading.get_ident()))
        return original_load(strict=strict)

    def execute(command, request):
        executed.append(request)
        return original_execute(command, request)

    monkeypatch.setattr(data, "load", load)
    monkeypatch.setattr(data, "save", Mock())
    monkeypatch.setattr(StatusCommand, "execute", execute)
    update = status_update()

    async def scenario():
        manager._message_lock = asyncio.Lock()
        await manager._message_lock.acquire()
        try:
            await asyncio.wait_for(manager.assess_message(update, None), 1)
        finally:
            manager._message_lock.release()

    asyncio.run(scenario())

    update.effective_message.reply_text.assert_awaited_once_with(
        f"Session: Active exposure sessions awaiting answers: 0\nSaved reports: {count}"
    )
    assert reads == [(True, reads[0][1])]
    assert reads[0][1] != main_thread
    assert len(executed) == 1 and executed[0].channel == "telegram"
    data.save.assert_not_called()
    assert manager._sessions == {}
    assert len(original_load(strict=True)) == count


def test_bot_status_counts_only_owned_live_pending_sessions_without_mutation(monkeypatch):
    monkeypatch.setattr(handlers_module, "time", SimpleNamespace(monotonic=lambda: 100))
    data = Mock(**{"load.return_value": [{}, {}, {}]})
    assessment = Mock()
    manager = TelegramIOManager(data, assessment=assessment)
    states = [
        {}, {"chat_id": 999}, {"user_id": 99}, {"expires_at": 99},
        {"expires_at": 100}, {"saved": True}, {"completed": True},
    ]
    for number, changes in enumerate(states):
        fields = {
            "chat_id": 123, "user_id": 42, "expires_at": 101,
            "completed": False, "saved": False, "lock": Mock(),
        }
        fields.update(changes)
        manager._sessions[str(number)] = SimpleNamespace(**fields)
    sessions = manager._sessions.copy()
    before = {key: value.__dict__.copy() for key, value in sessions.items()}
    update = status_update(" /status ignored ")

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_awaited_once_with(
        "Session: Active exposure sessions awaiting answers: 1\nSaved reports: 3"
    )
    assert manager._sessions == sessions
    assert {key: value.__dict__ for key, value in sessions.items()} == before
    data.load.assert_called_once_with(strict=True)
    data.save.assert_not_called()
    assessment.assess_with_findings.assert_not_called()


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_bot_status_read_failure_is_sanitized_without_zero_fallback(error_type):
    data = Mock(**{"load.side_effect": error_type("PRIVATE_ERROR")})
    assessment = Mock()
    manager = TelegramIOManager(data, assessment=assessment)
    update = status_update()

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_awaited_once_with(
        "Could not read local history. Please try again."
    )
    data.load.assert_called_once_with(strict=True)
    data.save.assert_not_called()
    assessment.assess_with_findings.assert_not_called()
    assert not manager._sessions


def test_bot_help_lists_status_metadata_once_without_history_reads():
    data = Mock()
    manager = TelegramIOManager(data)
    update = status_update("/help")

    asyncio.run(manager.assess_message(update, None))

    assert update.effective_message.reply_text.await_args.args[0].count(
        f"/status: {StatusCommand.help_text}"
    ) == 1
    data.load.assert_not_called()


def test_bot_pending_feedback_intercepts_status_without_history_read(monkeypatch):
    data = Mock()
    manager = TelegramIOManager(data)
    pending = {"assessment_id": "existing"}
    monkeypatch.setattr(manager, "_pending_feedback", Mock(return_value=pending))
    manager._submit_feedback = AsyncMock()
    update = status_update()

    asyncio.run(manager.assess_message(update, None))

    manager._submit_feedback.assert_awaited_once_with(update, None, pending, "/status")
    data.load.assert_not_called()
