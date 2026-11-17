"""Exercise main's real PTB dispatch without polling, credentials or network."""

import asyncio
import importlib
import json
import sys
import threading
from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Update
from telegram.ext import Application
from telegram.request import BaseRequest

from phishreport.bot.main import main
from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.data.factory import create_report_storage
from phishreport.io import IOManager, command_plugins
from phishreport.io.check_command import CheckCommand
from phishreport.io.help_command import HelpCommand

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
        token_length = len(text.split(maxsplit=1)[0].encode("utf-16-le")) // 2
        payload["entities"] = [{"type": "bot_command", "offset": 0, "length": token_length}]
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


def confirmation_callback(bot, pending, action, query_id):
    return Update.de_json({
        "update_id": 3000 + query_id,
        "callback_query": {
            "id": str(query_id), "from": USER, "chat_instance": "offline-chat",
            "data": f"exposure:{pending.token}:{action}",
            "message": {
                "message_id": pending.card_message_id, "date": 1,
                "chat": CHAT, "from": BOT, "text": "Check this message?",
            },
        },
    }, bot)


async def wait_for_cards(manager, request):
    await request.until(lambda: bool(manager._confirmations) and all(
        item.card_message_id is not None for item in manager._confirmations.values()
    ))


async def wait_for_sessions(manager, request):
    await request.until(lambda: bool(manager._sessions) and all(
        item.reply_message_id is not None for item in manager._sessions.values()
    ))


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
    "flags,action,expected_exposure,final_score,final_priority",
    [
        pytest.param(
            (True, True, False), "clicked",
            {"clicked": True, "downloaded": None,
             "submitted_category": None, "disclosure_answered": False},
            80, "HIGH", id="suspicious-clicked",
        ),
        pytest.param(
            (True, True, False), "password",
            {"clicked": None, "downloaded": None,
             "submitted_category": "password", "disclosure_answered": True},
            90, "HIGH", id="password",
        ),
        pytest.param(
            (True, True, False), "nothing", None, 60, "MEDIUM", id="suspicious-nothing",
        ),
        pytest.param(
            (False, False, False), "clicked",
            {"clicked": True, "downloaded": None,
             "submitted_category": None, "disclosure_answered": False},
            35, "MEDIUM", id="ordinary-clicked",
        ),
        pytest.param(
            (False, False, True), "nothing", None, 20, "LOW", id="insufficient-context",
        ),
    ],
)
def test_main_dispatch_exposure_acceptance(
    monkeypatch, tmp_path, backend, flags, action, expected_exposure,
    final_score, final_priority,
):
    """Real application routing confirms, saves the paste, then appends one revision."""
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, backend)
        suspicious, credential_request, insufficient_context = flags
        ai.assess.return_value = {
            "suspicious": suspicious,
            "credential_request": credential_request,
            "insufficient_context": insufficient_context,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        }
        initial_score = 60 if suspicious else 20 if insufficient_context else 10
        initial_priority = "MEDIUM" if suspicious else "LOW"
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
            await wait_for_cards(manager, request)
            pending, = manager._confirmations.values()
            card, = [data for endpoint, data in request.calls if endpoint == "sendMessage"]
            assert card["text"] == (
                "Check this message?\n\n"
                f'"{TEXT}"\n\n'
                "This text is sent to the AI provider for analysis."
            )
            assert [
                [button["text"] for button in row]
                for row in card["reply_markup"]["inline_keyboard"]
            ] == [["Yes, check it", "Cancel"]]
            assert ai.assess.call_count == 0 and writes == []
            assert manager._data_manager.load(strict=True) == []

            await asyncio.wait_for(
                app.process_update(confirmation_callback(app.bot, pending, "confirm", 1)), 2,
            )
            await wait_for_sessions(manager, request)
            await request.until(lambda: sum(
                endpoint == "editMessageText" for endpoint, _ in request.calls
            ) == 1)
            session, = manager._sessions.values()
            assert ("answerCallbackQuery", {"callback_query_id": "1"}) in request.calls
            initial = [data for endpoint, data in request.calls
                       if endpoint == "editMessageText"][-1]
            assert f"Priority: {initial_priority.title()}" in initial["text"]
            assert f"Rule-based score: {initial_score}" in initial["text"]
            assert "Provisional assessment." not in initial["text"]
            assert "Rule evaluation trace" not in initial["text"]
            assert "Unconfirmed" not in initial["text"]
            assert [
                [button["text"] for button in row]
                for row in initial["reply_markup"]["inline_keyboard"]
            ] == [["Clicked link", "Shared a password/OTP"], ["Nothing happened"]]
            assert ai.assess.call_count == 1
            initial_report, = writes
            assert initial_report["schema_version"] == 3
            assert initial_report["assessment_id"] == session.assessment_id
            assert initial_report["channel"] == "chat" and initial_report["message"] == TEXT
            assert initial_report["exposure"] == {
                "clicked": None, "downloaded": None,
                "submitted_category": None, "disclosure_answered": False,
            }
            assert initial_report["result"]["score"] == initial_score
            assert initial_report["result"]["priority"] == initial_priority
            assert manager._data_manager.load(strict=True) == [initial_report]

            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, action, 2)), 2,
            )
            await request.until(lambda: sum(
                endpoint == "editMessageText" for endpoint, _ in request.calls
            ) == 2)
            assert ("answerCallbackQuery", {"callback_query_id": "2"}) in request.calls
            final_edit = [data for endpoint, data in request.calls
                          if endpoint == "editMessageText"][-1]
            assert "Provisional assessment." not in final_edit["text"]
            assert "Report saved locally." not in final_edit["text"]
            assert "Unconfirmed" not in final_edit["text"]
            assert "expire" not in final_edit["text"].lower()
            assert f"Priority: {final_priority.title()}" in final_edit["text"]
            assert f"Rule-based score: {final_score}" in final_edit["text"]
            assert ai.assess.call_count == 1

            if action == "nothing":
                assert writes == [initial_report]
                assert final_edit.get("reply_markup") is None
                assert final_edit["text"].endswith("\n\nSaved. Nothing more to answer.")
                assert session.dismissed
            else:
                assert len(writes) == 2
                revised = writes[1]
                assert revised["assessment_id"] == initial_report["assessment_id"]
                assert revised["exposure"] == expected_exposure
                assert revised["result"]["score"] == final_score
                assert revised["result"]["priority"] == final_priority
                assert session.exposure == expected_exposure
                assert not session.dismissed
                if action == "password":
                    assert final_edit.get("reply_markup") is None
                    assert final_edit["text"].endswith("\n\nSaved. Nothing more to answer.")
                else:
                    assert [
                        [button["text"] for button in row]
                        for row in final_edit["reply_markup"]["inline_keyboard"]
                    ] == [["Shared a password/OTP", "Nothing else"]]
            assert session.saved and session.result["score"] == final_score

            frozen_writes = deepcopy(writes)
            frozen_state = deepcopy((session.result, session.exposure, session.report))
            edits_before = sum(
                endpoint == "editMessageText" for endpoint, _ in request.calls
            )
            if action == "clicked":
                # The card is still open, so replaying its answer rewrites it
                # once without another assessment or write.
                await asyncio.wait_for(
                    app.process_update(callback(app.bot, session, "clicked", 3)), 2,
                )
                await request.until(lambda: sum(
                    endpoint == "editMessageText" for endpoint, _ in request.calls
                ) == edits_before + 1)
                assert (
                    "answerCallbackQuery", {"callback_query_id": "3"}
                ) in request.calls
                assert writes == frozen_writes
                assert (session.result, session.exposure, session.report) == frozen_state
                assert ai.assess.call_count == 1
            else:
                # The keyboard is gone: any old answer is acknowledged and
                # changes nothing, with no second write.
                for query_id, stale in enumerate(
                    ("clicked", "password", "nothing"), 3,
                ):
                    await asyncio.wait_for(
                        app.process_update(callback(app.bot, session, stale, query_id)), 2,
                    )
                    await request.until(lambda: any(
                        endpoint == "answerCallbackQuery"
                        and data["callback_query_id"] == str(query_id)
                        for endpoint, data in request.calls
                    ))
                    assert sum(
                        endpoint == "editMessageText" for endpoint, _ in request.calls
                    ) == edits_before
                    assert writes == frozen_writes
                    assert (session.result, session.exposure, session.report) == frozen_state
                    assert ai.assess.call_count == 1
            await asyncio.wait_for(app.process_update(source), 2)
        finally:
            # stop drains PTB's nonblocking tasks, including replayed source delivery.
            await asyncio.wait_for(app.stop(), 5)
            await asyncio.wait_for(app.shutdown(), 3)
        assert not app.running and not errors
        assert ai.assess.call_count == 1 and writes == frozen_writes
        assert (session.result, session.exposure, session.report) == frozen_state
        assert len(manager._sessions) == 1
        assert sum(endpoint == "sendMessage" for endpoint, _ in request.calls) == 1
        reopened = DataManager(create_report_storage())
        assert reopened.load(strict=True) == frozen_writes

    asyncio.run(asyncio.wait_for(scenario(), 20))


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_main_dispatch_stays_responsive_during_exposure_storage(monkeypatch, tmp_path, backend):
    """Blocking a follow-up save must not block commands or new reports."""
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
            if report["exposure"]["clicked"] is not True:
                return actual_save(report)
            ack_before_write.append(
                ("answerCallbackQuery", {"callback_query_id": "2"}) in request.calls
            )
            writes.append(deepcopy(report))
            loop.call_soon_threadsafe(started.set)
            assert release.wait(8), "storage barrier was not released"
            actual_save(report)

        monkeypatch.setattr(manager._data_manager, "save", blocked_save)
        try:
            await asyncio.wait_for(app.process_update(message(app.bot, 100)), 2)
            await wait_for_cards(manager, request)
            pending, = manager._confirmations.values()
            await asyncio.wait_for(
                app.process_update(confirmation_callback(app.bot, pending, "confirm", 1)), 2,
            )
            await wait_for_sessions(manager, request)
            session, = manager._sessions.values()
            assert ai.assess.call_count == 1
            assert session.saved and session.result["score"] == 60
            initial, = manager._data_manager.load(strict=True)
            assert initial["result"]["priority"] == "MEDIUM"

            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, "clicked", 2)), 2,
            )
            await asyncio.wait_for(started.wait(), 3)
            assert ack_before_write == [True]
            assert len(writes) == 1 and not release.is_set()
            assert session.result["score"] == 60
            assert ai.assess.call_count == 1

            await asyncio.wait_for(app.process_update(message(app.bot, 101)), 2)
            await wait_for_cards(manager, request)
            await asyncio.wait_for(app.process_update(message(app.bot, 102, "/start")), 2)
            assert any(endpoint == "sendMessage" and "Welcome" in data["text"]
                       for endpoint, data in request.calls)
            assert not release.is_set()
            # The unconfirmed paste waits for a tap, so it runs no AI and no save.
            assert ai.assess.call_count == 1
            assert len(writes) == 1 and len(manager._sessions) == 1
            release.set()
            await request.until(lambda: session.result["score"] == 80)
            second, = manager._confirmations.values()
            second_confirm = confirmation_callback(app.bot, second, "confirm", 3)
            await asyncio.wait_for(app.process_update(second_confirm), 2)
            await request.until(lambda: len(manager._sessions) == 2)
            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, "password", 4)), 2,
            )
            await request.until(lambda: session.result["score"] == 90)
            for query_id, action in ((5, "finish"), (6, "retry")):
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
        assert ai.assess.call_count == 2
        initial, clicked_revision, second_initial, revised = manager._data_manager.load(strict=True)
        assert [report["result"]["score"] for report in
                (initial, clicked_revision, second_initial, revised)] == [60, 80, 60, 90]
        assert initial["schema_version"] == 3
        assert initial["assessment_id"] == clicked_revision["assessment_id"]
        assert initial["assessment_id"] == revised["assessment_id"]
        assert second_initial["assessment_id"] != initial["assessment_id"]
        assert second_initial["result"]["score"] == 60
        assert initial["channel"] == "chat" and initial["message"] == TEXT
        assert initial["result"]["score"] == 60
        assert revised["schema_version"] == 3
        assert revised["assessment_id"]
        assert revised["channel"] == "chat" and revised["message"] == TEXT
        assert revised["has_link"] and revised["link"] == "https://example.test/login"
        assert revised["has_file"] and revised["file_name"] == "invoice.pdf"
        assert revised["exposure"] == {
            "clicked": True, "downloaded": None,
            "submitted_category": "password", "disclosure_answered": True,
        }
        assert revised["result"]["score"] == 90 and revised["result"]["priority"] == "HIGH"

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
            await wait_for_cards(manager, request)
            pending, = manager._confirmations.values()
            await asyncio.wait_for(app.process_update(message(app.bot, 101, "/start")), 2)
            assert any(endpoint == "sendMessage" and "Welcome" in data["text"]
                       for endpoint, data in request.calls)
            assert not release.is_set() and not manager._sessions
            await asyncio.wait_for(
                app.process_update(confirmation_callback(app.bot, pending, "confirm", 1)), 2,
            )
            await asyncio.wait_for(started.wait(), 3)
            assert not manager._sessions
            release.set()
            await wait_for_sessions(manager, request)
        finally:
            release.set()
            await asyncio.wait_for(app.stop(), 5)
            await app.shutdown()
        assert not app.running
        assert not errors and ai.assess.call_count == 1
        saved, = manager._data_manager.load(strict=True)
        assert saved["result"]["priority"] == "MEDIUM"
        assert saved["message"] == TEXT

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
            await wait_for_cards(manager, request)
            pending, = manager._confirmations.values()
            await asyncio.wait_for(
                app.process_update(confirmation_callback(app.bot, pending, "confirm", 1)), 2,
            )
            await wait_for_sessions(manager, request)
            session, = manager._sessions.values()
            await asyncio.wait_for(
                app.process_update(callback(app.bot, session, action, 2)), 2,
            )
            await request.until(lambda: sum(
                endpoint == "editMessageText" for endpoint, _ in request.calls
            ) == 2)
            await request.until(lambda: any(
                endpoint == "answerCallbackQuery" and data["callback_query_id"] == "2"
                for endpoint, data in request.calls
            ))
            edit = [data for endpoint, data in request.calls if endpoint == "editMessageText"][-1]
            assert edit["text"] == (
                "This assessment is closed. "
                "Paste the message again to start a new assessment."
            )
            assert session.exposure["clicked"] is None
            assert session.saved and not session.dismissed
        finally:
            await asyncio.wait_for(app.stop(), 5)
            await app.shutdown()
        assert not app.running
        assert not errors and ai.assess.call_count == 1
        saved, = manager._data_manager.load(strict=True)
        assert saved["result"]["priority"] == "MEDIUM"

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("prefix", ["", "/check   ", "/unknown "])
def test_main_shared_command_dispatch_preserves_content_and_exposure_save(
    monkeypatch, tmp_path, backend, prefix,
):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, backend)
        pasted = "Mixed CASE https://example.test/login  "
        raw = prefix + pasted
        expected = pasted if prefix.startswith("/check") else raw
        await app.initialize()
        await app.start()
        try:
            await app.process_update(message(app.bot, 100, raw))
            await request.until(lambda: any(e == "sendMessage" for e, _ in request.calls))
            if prefix.startswith("/check"):
                session, = manager._sessions.values()
                initial_reply = next(
                    data["text"] for endpoint, data in request.calls if endpoint == "sendMessage"
                )
                query_id = 1
            else:
                await wait_for_cards(manager, request)
                pending, = manager._confirmations.values()
                card = next(
                    data["text"] for endpoint, data in request.calls if endpoint == "sendMessage"
                )
                assert "Check this message?" in card
                ai.assess.assert_not_called()
                assert manager._data_manager.load(strict=True) == []
                await app.process_update(confirmation_callback(app.bot, pending, "confirm", 1))
                await wait_for_sessions(manager, request)
                await request.until(lambda: any(e == "editMessageText" for e, _ in request.calls))
                session, = manager._sessions.values()
                initial_reply = [
                    data["text"] for endpoint, data in request.calls
                    if endpoint == "editMessageText"
                ][-1]
                query_id = 2
            assert session.record["message"] == expected
            assert "Priority: Medium" in initial_reply
            assert "Exposure unconfirmed" not in initial_reply
            initial, = manager._data_manager.load(strict=True)
            assert initial["message"] == expected
            assert initial["result"]["priority"] == "MEDIUM"
            await app.process_update(callback(app.bot, session, "clicked", query_id))
            await request.until(lambda: any(e == "editMessageText" for e, _ in request.calls))
            await request.until(lambda: session.result["score"] == 80)
            await request.until(lambda: len(manager._data_manager.load(strict=True)) == 2)
            initial, saved = manager._data_manager.load(strict=True)
            assert initial["assessment_id"] == saved["assessment_id"]
            assert saved["message"] == expected
            assert saved["exposure"]["clicked"] is True
            assert saved["result"]["priority"] == "HIGH"
            ai.assess.assert_called_once()
        finally:
            await app.stop()
            await app.shutdown()
        assert not errors

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_main_help_dispatch_uses_shared_metadata_without_assessment(monkeypatch, tmp_path):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        await app.initialize()
        await app.start()
        try:
            await app.process_update(message(app.bot, 100, "/help"))
            await request.until(lambda: any(e == "sendMessage" for e, _ in request.calls))
            reply = next(data["text"] for e, data in request.calls if e == "sendMessage")
            assert f"/check: {CheckCommand.help_text}" in reply
            assert f"/help: {HelpCommand.help_text}" in reply
            assert not manager._sessions and not manager._data_manager.load(strict=True)
            ai.assess.assert_not_called()
        finally:
            await app.stop()
            await app.shutdown()
        assert not errors

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("name", ["start", "linkgmail", "checkmail", "unlinkgmail"])
def test_main_existing_command_handlers_keep_precedence(monkeypatch, tmp_path, name):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        handler = next(item for item in app.handlers[0] if name in getattr(item, "commands", ()))
        original = handler.callback
        handler.callback = AsyncMock(wraps=original)
        await app.initialize()
        await app.start()
        try:
            update = message(app.bot, 100, "/" + name)
            await app.process_update(update)
            handler.callback.assert_awaited_once()
            ai.assess.assert_not_called()
            assert not manager._sessions
        finally:
            await app.stop()
            await app.shutdown()
        assert not errors

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.mark.parametrize("text", ["/help", "/check Feedback comment"])
def test_main_pending_feedback_keeps_shared_commands_as_comments(monkeypatch, tmp_path, text):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        pending = {"assessment_id": "existing"}
        app.user_data[USER["id"]]["pending_feedback"] = pending
        submitted = asyncio.Event()

        async def submit(*args):
            submitted.set()

        manager._submit_feedback = AsyncMock(side_effect=submit)
        await app.initialize()
        await app.start()
        try:
            await app.process_update(message(app.bot, 100, text))
            await asyncio.wait_for(submitted.wait(), 3)
            assert manager._submit_feedback.await_args.args[2:] == (pending, text)
            ai.assess.assert_not_called()
            assert not manager._sessions
        finally:
            await app.stop()
            await app.shutdown()
        assert not errors

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_main_shared_commands_ignore_disallowed_chat(monkeypatch, tmp_path):
    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, "json")
        await app.initialize()
        await app.start()
        try:
            update = message(app.bot, 100, "/check Content").to_dict()
            update["message"]["chat"]["id"] = 999
            await app.process_update(Update.de_json(update, app.bot))
        finally:
            await app.stop()
            await app.shutdown()
        ai.assess.assert_not_called()
        assert not manager._sessions and not errors
        assert not any(e == "sendMessage" for e, _ in request.calls)

    asyncio.run(asyncio.wait_for(scenario(), 10))


@pytest.fixture
def one_file_command(tmp_path, monkeypatch):
    """Install exactly one trusted module for both production transport paths."""
    module_name = "phishreport.io.command_plugins.zz_shared_one_file_probe"
    attribute = module_name.rsplit(".", 1)[-1]
    assert module_name not in sys.modules
    (tmp_path / f"{attribute}.py").write_text(
        "from phishreport.io.commands import Command, CommandReply\n"
        "EXECUTIONS = []\n"
        "class ProbeCommand(Command):\n"
        "    name = 'one_file_probe'\n"
        "    help_text = 'One file shared by both transports'\n"
        "    def execute(self, request):\n"
        "        EXECUTIONS.append((request.channel, request.text, type(self)))\n"
        "        return CommandReply('Echo: ' + request.text, 'text')\n"
        "def create_command(capabilities):\n"
        "    return ProbeCommand()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(command_plugins, "__path__", [*command_plugins.__path__, str(tmp_path)])
    importlib.invalidate_caches()
    try:
        yield import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)
        if hasattr(command_plugins, attribute):
            delattr(command_plugins, attribute)
        importlib.invalidate_caches()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_one_file_extends_cli_telegram_help_and_menu_without_changing_free_text(
    monkeypatch, tmp_path, backend, one_file_command,
):
    """One temporary command file requires no transport registration changes."""
    payload = "Mixed CASE  payload "
    seed = {
        "schema_version": 2, "channel": "chat", "message": "Existing history",
        "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
    }
    storage = JsonReportStorage if backend == "json" else SqliteReportStorage
    cli_data = DataManager(storage(tmp_path / "cli_history"))
    cli_data.save(seed)
    cli_save = Mock(wraps=cli_data.save)
    monkeypatch.setattr(cli_data, "save", cli_save)
    terminal = Mock()
    terminal.read.side_effect = ["  /one_file_probe   " + payload, "/help", "7"]
    cli_ai, cli_logic = Mock(), Mock()
    module = import_module("phishreport.bot.main")
    monkeypatch.setattr(module.AppLogging, "setup", lambda: True)
    cli_app = PhishReportApp(
        IOManager(terminal), cli_ai, cli_logic, cli_data, env_loader=Mock(),
    )

    cli_app.run()

    terminal.write.assert_any_call("Echo: " + payload)
    cli_help, = [entry.args[0] for entry in terminal.write.call_args_list
                 if "/one_file_probe:" in str(entry.args[0])]
    assert cli_help.count("/one_file_probe: One file shared by both transports") == 1
    cli_ai.assess.assert_not_called()
    cli_logic.evaluate.assert_not_called()
    cli_save.assert_not_called()
    assert cli_data.load(strict=True) == [seed]
    assert one_file_command.EXECUTIONS == [("cli", payload, one_file_command.ProbeCommand)]

    async def scenario():
        app, manager, ai, request, errors = offline_application(monkeypatch, tmp_path, backend)
        manager._data_manager.save(seed)
        bot_save = Mock(wraps=manager._data_manager.save)
        monkeypatch.setattr(manager._data_manager, "save", bot_save)
        builder = Mock(wraps=manager._record_builder)
        monkeypatch.setattr(manager, "_record_builder", builder)
        startup = SimpleNamespace(
            bot=SimpleNamespace(set_my_commands=AsyncMock(), username="offline_bot"), bot_data={},
        )
        monitor = Mock(run=AsyncMock())
        with patch.object(module, "EmailMonitor", return_value=monitor):
            await app.post_init(startup)
            await startup.bot_data["monitor_task"]
            await app.post_shutdown(startup)
        menu = startup.bot.set_my_commands.await_args.args[0]
        probe_entries = [entry for entry in menu if entry.command == "one_file_probe"]
        assert len(probe_entries) == 1
        assert probe_entries[0].description == "One file shared by both transports"
        assert one_file_command.EXECUTIONS == [("cli", payload, one_file_command.ProbeCommand)]
        ai.assess.assert_not_called()
        builder.build.assert_not_called()

        await app.initialize()
        await app.start()
        try:
            await app.process_update(message(app.bot, 100, "/one_file_probe\t" + payload))
            await request.until(lambda: sum(e == "sendMessage" for e, _ in request.calls) == 1)
            echo, = [data["text"] for e, data in request.calls if e == "sendMessage"]
            assert echo == "Echo: " + payload
            await app.process_update(message(app.bot, 101, "/help"))
            await request.until(lambda: sum(e == "sendMessage" for e, _ in request.calls) == 2)
            bot_help = [data["text"] for e, data in request.calls if e == "sendMessage"][-1]
            assert bot_help.count("/one_file_probe: One file shared by both transports") == 1
            assert one_file_command.EXECUTIONS == [
                ("cli", payload, one_file_command.ProbeCommand),
                ("telegram", payload, one_file_command.ProbeCommand),
            ]
            ai.assess.assert_not_called()
            builder.build.assert_not_called()
            assert not manager._sessions
            bot_save.assert_not_called()
            assert manager._data_manager.load(strict=True) == [seed]

            original = "  Untouched plain CASE\nKeep  spaces  "
            await app.process_update(message(app.bot, 102, original))
            await wait_for_cards(manager, request)
            builder.build.assert_called_once_with(original)
            ai.assess.assert_not_called()
            assert not manager._sessions
            bot_save.assert_not_called()
            card = [data["text"] for e, data in request.calls if e == "sendMessage"][-1]
            assert "Check this message?" in card
            pending, = manager._confirmations.values()
            await app.process_update(confirmation_callback(app.bot, pending, "confirm", 1))
            await wait_for_sessions(manager, request)
            ai.assess.assert_called_once()
            session, = manager._sessions.values()
            assert session.record["message"] == original and session.findings == FINDINGS
            assert session.saved and not session.dismissed
            bot_save.assert_called_once()
            saved, = bot_save.call_args.args
            assert saved["message"] == original
            assert saved["result"]["priority"] == "MEDIUM"
            assert manager._data_manager.load(strict=True) == [seed, saved]
        finally:
            await app.stop()
            await app.shutdown()
        assert not errors

    asyncio.run(asyncio.wait_for(scenario(), 15))
