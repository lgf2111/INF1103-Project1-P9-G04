"""Exercise main's real PTB dispatch without polling, credentials or network."""

import asyncio
import json
import threading
from copy import deepcopy
from importlib import import_module
from unittest.mock import Mock, patch

import pytest
from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest

from phishreport.bot.main import main
from phishreport.data import DataManager
from phishreport.data.factory import create_report_storage

CHAT = {"id": 12345, "type": "private"}
USER = {"id": 42, "is_bot": False, "first_name": "Reporter"}
BOT = {"id": 123, "is_bot": True, "first_name": "Offline", "username": "offline_bot"}
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}
TEXT = "Verify your password at https://example.test/login using invoice.pdf"


class OfflineRequest(BaseRequest):
    """Only the Bot API calls needed by these dispatch scenarios are accepted."""

    def __init__(self):
        self.calls = []
        self.changed = asyncio.Event()
        self.message_id = 1000

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        parameters = request_data.parameters if request_data else {}
        self.calls.append((endpoint, deepcopy(parameters)))
        self.changed.set()
        if endpoint == "getMe":
            result = BOT
        elif endpoint in {"sendMessage", "editMessageText"}:
            self.message_id += 1
            result = {
                "message_id": parameters.get("message_id", self.message_id),
                "date": 1, "chat": CHAT, "from": BOT, "text": parameters["text"],
            }
        elif endpoint == "answerCallbackQuery":
            result = True
        else:
            raise AssertionError(f"Unexpected offline Bot API method: {endpoint}")
        return 200, json.dumps({"ok": True, "result": result}).encode()

    async def until(self, predicate):
        while not predicate():
            self.changed.clear()
            await asyncio.wait_for(self.changed.wait(), 3)


def message(bot, message_id, text=TEXT):
    payload = {
        "message_id": message_id, "date": 1, "chat": CHAT, "from": USER, "text": text,
    }
    if text.startswith("/"):
        payload["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text)}]
    return Update.de_json({"update_id": message_id, "message": payload}, bot)


def callback(bot, session, action, query_id):
    return Update.de_json({
        "update_id": 2000 + query_id,
        "callback_query": {
            "id": str(query_id), "from": USER, "chat_instance": "offline-chat",
            "data": f"exposure:{session.token}:{action}",
            "message": {
                "message_id": session.reply_message_id, "date": 1,
                "chat": CHAT, "from": BOT, "text": "Questions",
            },
        },
    }, bot)


def offline_application(monkeypatch, tmp_path, backend):
    """Keep main's real composition; replace only external AI and HTTP I/O."""
    module = import_module("phishreport.bot.main")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "12345")
    monkeypatch.setenv("PHISHREPORT_STORAGE", backend)
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(tmp_path / "reports.json"))
    monkeypatch.setenv("PHISHREPORT_GMAIL_PATH", str(tmp_path / "gmail.json"))
    monkeypatch.setattr(module.AppLogging, "setup", lambda: None)
    ai = Mock(**{"assess.return_value": FINDINGS})
    monkeypatch.setattr(module, "AIManager", lambda: ai)
    request = OfflineRequest()
    # No bot/token is preconfigured: main remains responsible for .token(...).
    builder = Application.builder().request(request).get_updates_request(OfflineRequest())
    with patch.object(Application, "builder", return_value=builder), patch.object(
        Application, "run_polling", autospec=True,
    ) as polling:
        assert main() == 0
    app, = polling.call_args.args
    manager = app.handlers[0][0].callback.__self__
    errors = []

    async def collect_error(update, context):
        errors.append(context.error)

    app.error_handlers.clear()
    app.add_error_handler(collect_error)
    assert app.update_processor.max_concurrent_updates == 1
    return app, manager, ai, request, errors


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize(
    "flags,actions,answers,score,priority",
    [
        pytest.param((True, True, False), ("clicked", "finish"),
                     (True, False, None, False), 80, "HIGH", id="suspicious-clicked"),
        pytest.param((True, True, False), ("downloaded", "finish"),
                     (False, True, None, False), 80, "HIGH", id="suspicious-downloaded"),
        pytest.param((True, True, False), ("password", "finish"),
                     (None, None, "password", True), 90, "HIGH", id="password"),
        pytest.param((True, True, False), ("otp", "finish"),
                     (None, None, "otp", True), 90, "HIGH", id="otp"),
        pytest.param((True, True, False), ("skip",),
                     (None, None, None, False), 60, "MEDIUM", id="fully-skipped"),
        pytest.param((True, True, False), ("clicked", "skip"),
                     (True, False, None, False), 80, "HIGH", id="partial-skip"),
        pytest.param((True, True, False), ("neither", "no_disclosure", "finish"),
                     (False, False, None, True), 60, "MEDIUM", id="confirmed-none"),
        pytest.param((False, False, False), ("clicked", "finish"),
                     (True, False, None, False), 35, "MEDIUM", id="ordinary-clicked"),
        pytest.param((False, False, False), ("skip",),
                     (None, None, None, False), 10, "LOW", id="ordinary-skipped"),
        pytest.param((False, False, True), ("skip",),
                     (None, None, None, False), 20, "LOW", id="insufficient-context"),
    ],
)
def test_main_dispatch_exposure_acceptance(
    monkeypatch, tmp_path, backend, flags, actions, answers, score, priority,
):
    """Real application routing completes, freezes and persists honest answers."""
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, backend)
        suspicious, credential_request, insufficient_context = flags
        ai.assess.return_value = {
            "suspicious": suspicious,
            "credential_request": credential_request,
            "insufficient_context": insufficient_context,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        }
        clicked, downloaded, submitted_category, disclosure_answered = answers
        expected_exposure = {
            "clicked": clicked, "downloaded": downloaded,
            "submitted_category": submitted_category,
            "disclosure_answered": disclosure_answered,
        }
        writes = []
        actual_save = manager._data_manager.save

        def record_save(report):
            writes.append(deepcopy(report))
            actual_save(report)

        monkeypatch.setattr(manager._data_manager, "save", record_save)
        await app.initialize()
        await app.start()  # No polling, Gmail monitor or post_init.
        try:
            source = message(app.bot, 100)
            await asyncio.wait_for(app.process_update(source), 2)
            await request.until(lambda: bool(manager._sessions) and all(
                item.reply_message_id is not None for item in manager._sessions.values()
            ))
            session, = manager._sessions.values()
            initial, = [data for endpoint, data in request.calls if endpoint == "sendMessage"]
            assert "Provisional assessment." in initial["text"]
            assert "Did you click the link / download the file?" in initial["text"]
            assert "Did you enter a password or code?" in initial["text"]
            assert initial["reply_markup"]
            assert ai.assess.call_count == 1
            assert not writes and not manager._data_manager.load(strict=True)

            for query_id, action in enumerate(actions, 1):
                await asyncio.wait_for(
                    app.process_update(callback(app.bot, session, action, query_id)), 2,
                )
                # An API edit completes each nonblocking handler before the next answer.
                await request.until(lambda: sum(
                    endpoint == "editMessageText" for endpoint, _ in request.calls
                ) == query_id)
                assert (
                    "answerCallbackQuery", {"callback_query_id": str(query_id)}
                ) in request.calls
                assert ai.assess.call_count == 1
                if action not in {"finish", "skip"}:
                    assert not writes and not manager._data_manager.load(strict=True)

            assert session.completed and session.saved
            report, = writes
            assert report == {
                "schema_version": 3, "channel": "chat", "message": TEXT, "sender": None,
                "has_link": True, "link": "https://example.test/login",
                "has_file": True, "file_name": "invoice.pdf",
                "exposure": expected_exposure, "result": session.result,
            }
            assert report["result"]["score"] == score
            assert report["result"]["priority"] == priority
            final_edit = [data for endpoint, data in request.calls
                          if endpoint == "editMessageText"][-1]
            assert "Report saved locally." in final_edit["text"]
            assert f"Priority: {priority.title()}" in final_edit["text"]
            assert f"Rule-based score: {score}" in final_edit["text"]
            assert "Provisional assessment." not in final_edit["text"]
            unconfirmed = clicked is None or downloaded is None or not disclosure_answered
            assert ("Unconfirmed" in final_edit["text"]) is unconfirmed
            assert ("Exposure unconfirmed" in final_edit["text"]) is unconfirmed
            assert final_edit.get("reply_markup") is None

            frozen_report = deepcopy(report)
            frozen_result = deepcopy(session.result)
            frozen_exposure = deepcopy(session.exposure)
            # Saved buttons can arrive late, including an answer that would change the score.
            for query_id, action in enumerate(("finish", "skip", "retry", "both", "otp"),
                                              len(actions) + 1):
                await asyncio.wait_for(
                    app.process_update(callback(app.bot, session, action, query_id)), 2,
                )
                await request.until(lambda: sum(
                    endpoint == "editMessageText" for endpoint, _ in request.calls
                ) == query_id)
                assert session.report == frozen_report
                assert session.result == frozen_result and session.exposure == frozen_exposure
                assert ai.assess.call_count == 1 and writes == [frozen_report]
            await asyncio.wait_for(app.process_update(source), 2)
        finally:
            # stop drains PTB's nonblocking tasks, including replayed source delivery.
            await asyncio.wait_for(app.stop(), 5)
            await asyncio.wait_for(app.shutdown(), 3)
        assert not app.running and not errors
        assert ai.assess.call_count == 1 and writes == [frozen_report]
        assert session.report == frozen_report
        assert session.result == frozen_result and session.exposure == frozen_exposure
        assert len(manager._sessions) == 1
        assert sum(endpoint == "sendMessage" for endpoint, _ in request.calls) == 1
        reopened = DataManager(create_report_storage())
        assert reopened.load(strict=True) == [frozen_report]

    asyncio.run(asyncio.wait_for(scenario(), 20))


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_main_dispatch_stays_responsive_during_exposure_storage(monkeypatch, tmp_path, backend):
    """Blocking either registered handler would prevent commands/new reports."""
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, backend)
        await app.initialize()
        await app.start()  # Deliberately do not invoke post_init: no Gmail monitor/polling.
        release = threading.Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        actual_save = manager._data_manager.save
        writes = []
        ack_before_write = []

        def blocked_save(report):
            ack_before_write.append(
                ("answerCallbackQuery", {"callback_query_id": "3"}) in request.calls
            )
            writes.append(deepcopy(report))
            loop.call_soon_threadsafe(started.set)
            assert release.wait(8), "storage barrier was not released"
            actual_save(report)

        monkeypatch.setattr(manager._data_manager, "save", blocked_save)
        try:
            await asyncio.wait_for(app.process_update(message(app.bot, 100)), 2)
            await request.until(lambda: bool(manager._sessions) and all(
                session.reply_message_id is not None for session in manager._sessions.values()
            ))
            session, = manager._sessions.values()
            assert ai.assess.call_count == 1
            assert not manager._data_manager.load(strict=True)

            # All updates go through PTB's actual process_update routing.
            for query_id, action in ((1, "clicked"), (2, "password")):
                await asyncio.wait_for(
                    app.process_update(callback(app.bot, session, action, query_id)), 2,
                )
                await request.until(lambda: sum(
                    endpoint == "editMessageText" for endpoint, _ in request.calls
                ) >= query_id)
            assert session.result["score"] == 90
            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, "finish", 3)), 2,
            )
            await asyncio.wait_for(started.wait(), 3)
            assert ack_before_write == [True]
            assert not session.saved and not release.is_set()
            assert ai.assess.call_count == 1

            await asyncio.wait_for(app.process_update(message(app.bot, 101)), 2)
            await request.until(lambda: len(manager._sessions) == 2 and all(
                item.reply_message_id is not None for item in manager._sessions.values()
            ))
            await asyncio.wait_for(app.process_update(message(app.bot, 102, "/start")), 2)
            assert any(endpoint == "sendMessage" and "Welcome" in data["text"]
                       for endpoint, data in request.calls)
            assert not release.is_set() and not session.saved
            assert ai.assess.call_count == 2  # One AI call per distinct source, none for answers.
            assert len(writes) == 1
            release.set()
            await request.until(lambda: session.saved)
            for query_id, action in ((4, "finish"), (5, "retry")):
                await asyncio.wait_for(
                    app.process_update(callback(app.bot, session, action, query_id)), 2,
                )
                await request.until(lambda: any(
                    endpoint == "answerCallbackQuery" and data["callback_query_id"] == str(query_id)
                    for endpoint, data in request.calls
                ))
        finally:
            release.set()
            await asyncio.wait_for(app.stop(), 5)
            await app.shutdown()
        assert not app.running
        assert not errors
        assert "monitor_task" not in app.bot_data
        assert len(writes) == 1 and ai.assess.call_count == 2
        report, = manager._data_manager.load(strict=True)
        assert report["schema_version"] == 3
        assert report["channel"] == "chat" and report["message"] == TEXT
        assert report["has_link"] and report["link"] == "https://example.test/login"
        assert report["has_file"] and report["file_name"] == "invoice.pdf"
        assert report["exposure"] == {
            "clicked": True, "downloaded": False,
            "submitted_category": "password", "disclosure_answered": True,
        }
        assert report["result"]["score"] == 90 and report["result"]["priority"] == "HIGH"

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_main_dispatch_start_while_initial_ai_is_blocked(monkeypatch, tmp_path):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        await app.initialize()
        await app.start()
        release = threading.Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocked_ai(record):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(8), "AI barrier was not released"
            return FINDINGS

        ai.assess.side_effect = blocked_ai
        try:
            await asyncio.wait_for(app.process_update(message(app.bot, 100)), 2)
            await asyncio.wait_for(started.wait(), 3)
            await asyncio.wait_for(app.process_update(message(app.bot, 101, "/start")), 2)
            assert any(endpoint == "sendMessage" and "Welcome" in data["text"]
                       for endpoint, data in request.calls)
            assert not release.is_set() and not manager._sessions
            release.set()
            await request.until(lambda: bool(manager._sessions) and all(
                session.reply_message_id is not None for session in manager._sessions.values()
            ))
        finally:
            release.set()
            await asyncio.wait_for(app.stop(), 5)
            await app.shutdown()
        assert not app.running
        assert not errors and ai.assess.call_count == 1
        assert not manager._data_manager.load(strict=True)

    asyncio.run(asyncio.wait_for(scenario(), 15))


@pytest.mark.parametrize("action", ["unknown", "clicked\n", ""])
def test_main_dispatch_malformed_exposure_is_acknowledged_and_rejected(
    monkeypatch, tmp_path, action,
):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        await app.initialize()
        await app.start()
        try:
            await asyncio.wait_for(app.process_update(message(app.bot, 100)), 2)
            await request.until(lambda: bool(manager._sessions) and all(
                session.reply_message_id is not None for session in manager._sessions.values()
            ))
            session, = manager._sessions.values()
            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, action, 1)), 2,
            )
            await request.until(lambda: any(
                endpoint == "editMessageText" for endpoint, _ in request.calls
            ))
            assert ("answerCallbackQuery", {"callback_query_id": "1"}) in request.calls
            edit, = [data for endpoint, data in request.calls if endpoint == "editMessageText"]
            assert edit["text"] == (
                "These questions are not available. "
                "Paste the message again to start a new assessment."
            )
            assert session.exposure["clicked"] is None and not session.completed
        finally:
            await asyncio.wait_for(app.stop(), 5)
            await app.shutdown()
        assert not app.running
        assert not errors and ai.assess.call_count == 1
        assert not manager._data_manager.load(strict=True)

    asyncio.run(asyncio.wait_for(scenario(), 10))
