"""Exercise the Telegram welcome screen and check with offline updates."""

import asyncio
import os
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot import handlers as handlers_module
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.handlers import CHECK_CONNECTION, TelegramIOManager
from phishreport.bot.main import main
from phishreport.bot.messages import ChatRecordBuilder, ResultFormatter
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345

UNAVAILABLE_EXPOSURE = (
    "These questions are not available. Paste the message again to start a new assessment."
)


@pytest.fixture
def callback_setup(save_exposure_setup):
    manager, previous, ai = save_exposure_setup
    service = manager._assessment
    service.rescore = AssessmentService.rescore.__get__(service)
    session = ExposureSession(
        previous.record, AssessmentSnapshot(previous.findings, service.rescore(
            previous.record, previous.findings,
        )), chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=100,
    )
    session.reply_message_id = 1100
    manager._sessions[session.token] = session
    manager._source_sessions[(ALLOWED_CHAT_ID, 42, 100)] = session.token

    def update(action):
        result = lookup_update(message_id=1100, callback=True)
        result.callback_query = SimpleNamespace(
            data=f"exposure:{session.token}:{action}", answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        return result

    return manager, session, ai, update


@pytest.mark.parametrize("action,score", [
    ("clicked", 80), ("downloaded", 80), ("both", 80), ("neither", 60),
    ("password", 90), ("otp", 90), ("no_disclosure", 60), ("skip", 60),
])
def test_exposure_callback_real_scoring_once_and_frozen_completion(callback_setup, action, score):
    manager, session, ai, update = callback_setup

    async def scenario():
        answer = update(action)
        await manager.exposure_callback(answer, None)
        answer.callback_query.answer.assert_awaited_once_with()
        assert session.result["score"] == score
        for repeated in ("finish", "skip", "retry", "clicked"):
            await manager.exposure_callback(update(repeated), None)
        assert session.report["result"]["score"] == score
        assert session.report["exposure"] == session.exposure
        assert session.saved
        if action == "skip":
            assert session.report["result"]["priority"] == "MEDIUM"
            assert session.report["exposure"] == {
                "clicked": None, "downloaded": None,
                "submitted_category": None, "disclosure_answered": False,
            }

    asyncio.run(asyncio.wait_for(scenario(), 5))
    manager._data_manager.save.assert_called_once_with(session.report)
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("case", [
    "wrong_owner", "wrong_reply", "expired", "unknown_token", "unknown_action",
    "newline", "prefix", "token_length", "none_payload", "numeric_payload",
])
def test_exposure_callback_invalid_neutral_no_work(callback_setup, case):
    manager, session, ai, update = callback_setup
    incoming = update("clicked")
    if case == "wrong_owner":
        incoming.effective_user.id += 1
    elif case == "wrong_reply":
        incoming.effective_message.message_id += 1
    elif case == "expired":
        session.expires_at = 0
    else:
        incoming.callback_query.data = {
            "unknown_token": f"exposure:{'_' * 16}:clicked",
            "unknown_action": f"exposure:{session.token}:unknown",
            "newline": f"exposure:{session.token}:clicked\n",
            "prefix": f"other:{session.token}:clicked",
            "token_length": f"exposure:{session.token}a:clicked",
            "none_payload": None, "numeric_payload": 1,
        }[case]
    before = deepcopy(session.exposure)
    asyncio.run(manager.exposure_callback(incoming, None))
    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        UNAVAILABLE_EXPOSURE, reply_markup=None,
    )
    assert session.exposure == before and not session.completed
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("case", ["no_chat", "missing_type", "group", "disallowed"])
def test_exposure_callback_disallowed_ack_only(callback_setup, case):
    manager, session, _, update = callback_setup
    incoming = update("clicked")
    manager._allowed_chat_id = ALLOWED_CHAT_ID
    if case == "no_chat":
        incoming.effective_chat = None
    elif case == "missing_type":
        del incoming.effective_chat.type
    elif case == "group":
        incoming.effective_chat.type = "group"
    else:
        incoming.effective_chat.id += 1
    manager._find_exposure_session = Mock(side_effect=AssertionError("No lookup"))
    asyncio.run(manager.exposure_callback(incoming, None))
    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_not_awaited()
    assert not session.completed and session.exposure["clicked"] is None


@pytest.mark.parametrize("chat_id", ["absent", None, "12345", 12345.0, True, False])
def test_exposure_callback_invalid_chat_id_ack_only(callback_setup, chat_id):
    manager, session, ai, update = callback_setup
    manager._allowed_chat_id = ALLOWED_CHAT_ID
    incoming = update("clicked")
    if chat_id == "absent":
        del incoming.effective_chat.id
    else:
        incoming.effective_chat.id = chat_id
    before = (manager._sessions.copy(), manager._source_sessions.copy())
    manager._find_exposure_session = Mock(side_effect=AssertionError("No lookup"))
    asyncio.run(manager.exposure_callback(incoming, None))
    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_not_awaited()
    assert (manager._sessions, manager._source_sessions) == before
    assert session.exposure["clicked"] is None and not session.completed
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


def test_exposure_callback_no_query_and_failed_ack_never_lookup(callback_setup):
    manager, _, _, update = callback_setup
    manager._find_exposure_session = Mock(side_effect=AssertionError("No lookup"))

    async def scenario():
        await manager.exposure_callback(SimpleNamespace(), None)
        incoming = update("finish")
        incoming.callback_query.answer.side_effect = RuntimeError("ack failed")
        with pytest.raises(RuntimeError, match="ack failed"):
            await manager.exposure_callback(incoming, None)

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_exposure_callback_save_failure_retry_real_storage(callback_setup, tmp_path, backend):
    manager, session, ai, update = callback_setup
    manager._data_manager.save.side_effect = OSError("SECRET path")

    async def scenario():
        await manager.exposure_callback(update("password"), None)
        failed = update("finish")
        await manager.exposure_callback(failed, None)
        text = failed.callback_query.edit_message_text.call_args.args[0]
        assert "SECRET" not in text and "Retry saving" in text
        assert session.completed and not session.saved
        report = deepcopy(session.report)
        session.expires_at = 0
        storage = (JsonReportStorage(tmp_path / "history.json") if backend == "json"
                   else SqliteReportStorage(tmp_path / "history.sqlite3"))
        manager._data_manager = DataManager(storage)
        await manager.exposure_callback(update("retry"), None)
        assert session.saved and manager._data_manager.load(strict=True) == [report]

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("error", [OSError, ValueError, RuntimeError])
def test_exposure_callback_expected_answer_failure_safe_feedback(callback_setup, error):
    manager, session, _, update = callback_setup
    manager._assessment.rescore = Mock(side_effect=error("SECRET"))
    incoming = update("clicked")
    asyncio.run(manager.exposure_callback(incoming, None))
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert text.startswith("Could not update the assessment. Please try again.")
    assert "SECRET" not in text and text.endswith(ResultFormatter.FOOTER)
    assert len(text.encode("utf-16-le")) // 2 <= 4096
    assert session.exposure["clicked"] is None


def test_exposure_callback_retry_pending_and_missing_service_do_not_write(callback_setup):
    manager, session, _, update = callback_setup

    async def scenario():
        await manager.exposure_callback(update("retry"), None)
        assert not session.completed
        manager._assessment = None
        for action in ("clicked", "finish"):
            await manager.exposure_callback(update(action), None)
            assert not session.completed

    asyncio.run(scenario())
    manager._data_manager.save.assert_not_called()


@pytest.mark.parametrize("not_modified", [False, True])
def test_exposure_callback_telegram_failure_preserves_saved_state(callback_setup, not_modified):
    manager, session, ai, update = callback_setup

    async def scenario():
        incoming = update("finish")
        incoming.callback_query.edit_message_text.side_effect = BadRequest(
            "MESSAGE IS NOT MODIFIED" if not_modified else "edit unavailable",
        )
        if not_modified:
            await manager.exposure_callback(incoming, None)
        else:
            with pytest.raises(BadRequest, match="edit unavailable"):
                await manager.exposure_callback(incoming, None)
        assert session.saved
        await manager.exposure_callback(update("retry"), None)

    asyncio.run(scenario())
    manager._data_manager.save.assert_called_once()
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("action", ["clicked", "finish", "skip"])
def test_exposure_callback_ack_before_lock_expiry_while_waiting(callback_setup, action):
    manager, session, _, update = callback_setup
    incoming = update(action)

    async def scenario():
        async with session.lock:
            task = asyncio.create_task(manager.exposure_callback(incoming, None))
            await asyncio.sleep(0)
            incoming.callback_query.answer.assert_awaited_once_with()
            assert not task.done()
            session.expires_at = 0
        await task

    asyncio.run(asyncio.wait_for(scenario(), 5))
    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        UNAVAILABLE_EXPOSURE, reply_markup=None,
    )
    assert session.exposure["clicked"] is None
    manager._data_manager.save.assert_not_called()


def test_exposure_callback_concurrent_final_buttons_and_unrelated_start(callback_setup):
    manager, session, ai, update = callback_setup
    release = threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()

        def save(report):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5)

        manager._data_manager.save.side_effect = save
        first, second = update("finish"), update("skip")
        task = asyncio.create_task(manager.exposure_callback(first, None))
        try:
            await asyncio.wait_for(started.wait(), 3)
            first.callback_query.answer.assert_awaited_once_with()
            duplicate = asyncio.create_task(manager.exposure_callback(second, None))
            await asyncio.sleep(0)
            second.callback_query.answer.assert_awaited_once_with()
            welcome = fake_update()
            await asyncio.wait_for(manager.start(welcome, None), 1)
            welcome.effective_message.reply_text.assert_awaited_once()
            assert not duplicate.done()
        finally:
            release.set()
        await asyncio.gather(task, duplicate)
        for incoming in (first, second):
            assert "Report saved locally." in (
                incoming.callback_query.edit_message_text.call_args.args[0]
            )

    asyncio.run(asyncio.wait_for(scenario(), 8))
    manager._data_manager.save.assert_called_once()
    assert session.saved and ai.assess.call_count == 1


def test_exposure_callback_serialized_edits_preserve_current_answer(callback_setup):
    manager, session, ai, update = callback_setup
    edits = []

    async def scenario():
        editing, release = asyncio.Event(), asyncio.Event()
        first, second = update("clicked"), update("password")

        async def slow_edit(text, **kwargs):
            assert session.lock.locked()
            editing.set()
            await release.wait()
            edits.append(text)

        async def final_edit(text, **kwargs):
            assert session.lock.locked()
            edits.append(text)

        first.callback_query.edit_message_text.side_effect = slow_edit
        second.callback_query.edit_message_text.side_effect = final_edit
        task = asyncio.create_task(manager.exposure_callback(first, None))
        await editing.wait()
        duplicate = asyncio.create_task(manager.exposure_callback(second, None))
        await asyncio.sleep(0)
        second.callback_query.answer.assert_awaited_once_with()
        assert session.result["score"] == 80 and not duplicate.done()
        release.set()
        await asyncio.gather(task, duplicate)

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert "Information submitted: Unconfirmed" in edits[0]
    assert "Information submitted: Password" in edits[1]
    assert session.result["score"] == 90 and ai.assess.call_count == 1
    manager._data_manager.save.assert_not_called()


def test_exposure_callback_lookup_happens_after_ack(callback_setup):
    manager, _, _, update = callback_setup
    incoming = update("clicked")
    original = manager._find_exposure_session

    def find(*args):
        incoming.callback_query.answer.assert_awaited_once_with()
        return original(*args)

    manager._find_exposure_session = find
    asyncio.run(manager.exposure_callback(incoming, None))


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_exposure_callback_completion_failure_preserves_pending(callback_setup, error_type):
    manager, session, _, update = callback_setup
    manager._assessment.build_exposure_report = Mock(side_effect=error_type("SECRET"))
    incoming = update("finish")
    asyncio.run(manager.exposure_callback(incoming, None))
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert text.startswith("Could not update the assessment. Please try again.")
    assert "SECRET" not in text
    assert not session.completed and session.report is None
    manager._data_manager.save.assert_not_called()


def test_exposure_callback_failure_prefix_fits_maximum_formatted_reply(callback_setup):
    manager, session, _, update = callback_setup
    session.result["reasons"] = ["😀" * 10000]
    manager._assessment.rescore = Mock(side_effect=ValueError("SECRET"))
    incoming = update("clicked")
    asyncio.run(manager.exposure_callback(incoming, None))
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert 4000 < len(text.encode("utf-16-le")) // 2 <= 4096
    assert text.endswith(ResultFormatter.FOOTER)


@pytest.fixture
def save_exposure_setup():
    ai = Mock()
    ai.assess.return_value = {
        "suspicious": True, "credential_request": True, "insufficient_context": False,
    }
    service = AssessmentService(ai, LogicManager())
    record = ChatRecordBuilder().build("Verify https://example.test invoice.pdf", sender="Sender")
    session = ExposureSession(
        record, service.assess_with_findings(record),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=100,
    )
    session.apply_answer("clicked", service)
    service.rescore = Mock(side_effect=AssertionError("Must not re-score during save"))
    return TelegramIOManager(Mock(spec=DataManager), assessment=service), session, ai


def test_save_exposure_helper_concurrent_same_session_writes_once(save_exposure_setup):
    manager, session, ai = save_exposure_setup

    async def scenario():
        await asyncio.wait_for(asyncio.gather(*(
            manager._save_exposure_report(session) for _ in range(8)
        )), 5)

    asyncio.run(scenario())
    assert session.completed and session.saved
    manager._data_manager.save.assert_called_once()
    report = manager._data_manager.save.call_args.args[0]
    assert report["result"]["score"] == 80
    assert report["exposure"]["clicked"] is True
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("error_type", [OSError, ValueError])
@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_save_exposure_helper_real_storage_retry_uses_unmutated_cache(
    save_exposure_setup, tmp_path, backend, error_type,
):
    manager, session, ai = save_exposure_setup
    storage = (JsonReportStorage(tmp_path / "history.json") if backend == "json"
               else SqliteReportStorage(tmp_path / "history.sqlite3"))
    data = DataManager(storage)
    error = error_type("storage unavailable")

    def failing_save(report):
        report["result"]["score"] = 999
        report["exposure"]["clicked"] = False
        raise error

    manager._data_manager = SimpleNamespace(save=failing_save)

    async def scenario():
        with pytest.raises(error_type) as caught:
            await manager._save_exposure_report(session)
        assert caught.value is error
        assert session.completed and not session.saved
        assert session.report["result"]["score"] == 80
        assert session.report["exposure"]["clicked"] is True
        cached = deepcopy(session.report)
        session.expires_at = 0
        manager._data_manager = data
        await manager._save_exposure_report(session)
        await manager._save_exposure_report(session)
        assert data.load(strict=True) == [cached]

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert session.saved
    assert ai.assess.call_count == 1


def test_save_exposure_helper_guards_saved_missing_service_and_expired(save_exposure_setup):
    manager, session, _ = save_exposure_setup

    async def scenario():
        manager._assessment = None
        with pytest.raises(ValueError):
            await manager._save_exposure_report(session)
        assert not session.completed and session.report is None
        manager._assessment = Mock()
        session.expires_at = 0
        with pytest.raises(ValueError, match="expired"):
            await manager._save_exposure_report(session)
        assert not session.completed and session.report is None
        session.saved = True
        manager._assessment = None
        session.complete = Mock(side_effect=AssertionError("Saved must return immediately"))
        await manager._save_exposure_report(session)

    asyncio.run(asyncio.wait_for(scenario(), 5))
    manager._data_manager.save.assert_not_called()


def test_save_exposure_helper_completion_error_propagates(save_exposure_setup):
    manager, session, _ = save_exposure_setup
    error = ValueError("cannot complete")
    manager._assessment.build_exposure_report = Mock(side_effect=error)

    async def scenario():
        with pytest.raises(ValueError) as caught:
            await manager._save_exposure_report(session)
        assert caught.value is error

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert not session.completed and not session.saved and session.report is None
    manager._data_manager.save.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_save_exposure_helper_cancellation_waits_for_write_outcome(save_exposure_setup, failure):
    manager, session, ai = save_exposure_setup
    release = threading.Event()
    threads = []
    error = OSError("worker failed")

    async def scenario():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()

        def save(report):
            threads.append(threading.get_ident())
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise TimeoutError("Test did not release storage")
            if failure:
                raise error

        manager._data_manager.save.side_effect = save
        task = asyncio.create_task(manager._save_exposure_report(session))
        try:
            await asyncio.wait_for(started.wait(), 3)
            assert threads == [threads[0]] and threads[0] != threading.get_ident()
            task.cancel("first cancellation")
            await asyncio.sleep(0)
            task.cancel("second cancellation")
            await asyncio.sleep(0)
            assert not task.done() and not session.saved
            assert manager.save_lock.locked() and session.lock.locked()
            # A duplicate must remain blocked until the storage outcome is known.
            duplicate = asyncio.create_task(manager._save_exposure_report(session))
            await asyncio.sleep(0)
            assert not duplicate.done()
            duplicate.cancel()
            with pytest.raises(asyncio.CancelledError):
                await duplicate
        finally:
            release.set()
        if failure:
            with pytest.raises(OSError) as caught:
                await asyncio.wait_for(task, 3)
            assert caught.value is error
            assert not session.saved
        else:
            with pytest.raises(asyncio.CancelledError, match="first cancellation"):
                await asyncio.wait_for(task, 3)
            assert session.saved
            await manager._save_exposure_report(session)
        assert not manager.save_lock.locked() and not session.lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 10))
    manager._data_manager.save.assert_called_once()
    assert ai.assess.call_count == 1


def test_save_exposure_helper_cancel_waiting_global_lock_never_writes(save_exposure_setup):
    manager, session, _ = save_exposure_setup

    async def scenario():
        async with manager.save_lock:
            task = asyncio.create_task(manager._save_exposure_report(session))
            await asyncio.sleep(0)
            assert session.completed and session.lock.locked()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not session.saved and not session.lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    manager._data_manager.save.assert_not_called()


def test_save_exposure_helper_cancelled_worker_does_not_spin(save_exposure_setup):
    manager, session, _ = save_exposure_setup
    manager._data_manager.save.side_effect = asyncio.CancelledError("worker cancelled")

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await manager._save_exposure_report(session)
        assert session.completed and not session.saved
        assert not session.lock.locked() and not manager.save_lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 3))


def test_save_exposure_helper_sessions_and_gmail_share_serial_writer(save_exposure_setup):
    manager, session, _ = save_exposure_setup
    second = ExposureSession(
        session.record, AssessmentSnapshot(session.findings, session.result),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=101,
    )
    release = threading.Event()
    active = peak = 0
    calls = []

    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()

        def save(report):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append(report)
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("Test did not release storage")
            active -= 1

        manager._data_manager.save.side_effect = save

        async def gmail_writer():
            async with manager.save_lock:
                await asyncio.to_thread(manager._data_manager.save, {"channel": "email"})

        gmail = asyncio.create_task(gmail_writer())
        try:
            await asyncio.wait_for(entered.wait(), 3)
            tasks = [asyncio.create_task(manager._save_exposure_report(item))
                     for item in (session, second)]
            await asyncio.sleep(0)
            assert len(calls) == 1
            assert session.completed and second.completed
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(gmail, *tasks), 3)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert peak == 1 and active == 0 and len(calls) == 3
    assert session.saved and second.saved


def lookup_update(*, chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=100, callback=False):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="private"),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(message_id=message_id),
        callback_query=SimpleNamespace() if callback else None,
    )


def cache_lookup_session(manager, *, message_id=100, created_at=10, state="pending"):
    session = ExposureSession(
        {"message": "same text"}, AssessmentSnapshot(findings={}, result={"score": 0}),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=message_id,
    )
    session.created_at = created_at
    session.expires_at = 200
    session.reply_message_id = message_id + 1000
    session.completed = state in {"saved", "retry"}
    session.saved = state == "saved"
    manager._sessions[session.token] = session
    manager._source_sessions[(session.chat_id, session.user_id, message_id)] = session.token
    return session


def test_exposure_lookup_source_replay_and_callback_use_distinct_message_ids(monkeypatch):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    clock = Mock(return_value=100)
    monkeypatch.setattr(handlers_module, "time", SimpleNamespace(monotonic=clock), raising=False)

    assert manager._find_exposure_session(lookup_update()) is session
    assert manager._find_exposure_session(
        lookup_update(message_id=1100, callback=True), session.token
    ) is session
    assert clock.call_count == 2
    assert manager._data_manager.mock_calls == []


@pytest.mark.parametrize("missing", ["effective_chat", "effective_user", "effective_message"])
@pytest.mark.parametrize("absent", [False, True])
def test_exposure_lookup_missing_identity_is_unchanged(missing, absent):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    session.expires_at = 0
    update = lookup_update()
    if absent:
        delattr(update, missing)
    else:
        setattr(update, missing, None)
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(update) is None
    assert (manager._sessions, manager._source_sessions) == before


@pytest.mark.parametrize("field", ["chat_id", "user_id", "message_id"])
@pytest.mark.parametrize("value", [None, True, "100", 100.0])
def test_exposure_lookup_requires_exact_integer_update_ids(field, value):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    session.expires_at = 0
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(lookup_update(**{field: value})) is None
    assert (manager._sessions, manager._source_sessions) == before


@pytest.mark.parametrize("chat_type", ["absent", None, "invalid"])
@pytest.mark.parametrize("callback", [False, True])
def test_exposure_lookup_malformed_chat_type_is_unchanged(chat_type, callback, monkeypatch):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    session.expires_at = 0
    update = lookup_update(message_id=1100 if callback else 100, callback=callback)
    if chat_type == "absent":
        del update.effective_chat.type
    else:
        update.effective_chat.type = chat_type
    clock = Mock(side_effect=AssertionError("Invalid identity must not trigger cleanup"))
    monkeypatch.setattr(handlers_module, "time", SimpleNamespace(monotonic=clock))
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(update, session.token if callback else None) is None
    assert (manager._sessions, manager._source_sessions) == before


@pytest.mark.parametrize("case", [
    "group", "disallowed", "source_callback", "callback_missing", "wrong_user",
    "wrong_chat", "wrong_reply", "source_id_as_reply", "missing_reply", "source_mismatch",
])
def test_exposure_lookup_invalid_routing_never_cleans_caches(case):
    manager = TelegramIOManager(Mock(spec=DataManager), ALLOWED_CHAT_ID)
    session = cache_lookup_session(manager)
    expired = cache_lookup_session(manager, message_id=101)
    expired.expires_at = 0
    update = lookup_update(message_id=1100, callback=True)
    token = session.token
    if case == "group":
        update.effective_chat.type = "group"
    elif case == "disallowed":
        update.effective_chat.id += 1
    elif case == "source_callback":
        token = None
        update.effective_message.message_id = 100
    elif case == "callback_missing":
        update.callback_query = None
    elif case == "wrong_user":
        update.effective_user.id += 1
    elif case == "wrong_chat":
        manager._allowed_chat_id = None
        update.effective_chat.id += 1
    elif case == "wrong_reply":
        update.effective_message.message_id = 999
    elif case == "source_id_as_reply":
        update.effective_message.message_id = 100
    elif case == "missing_reply":
        session.reply_message_id = None
    else:
        update = lookup_update()
        token = None
        session.message_id = 999
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(update, token) is None
    assert (manager._sessions, manager._source_sessions) == before


@pytest.mark.parametrize("token", ["", "a" * 15, "a" * 17, "a" * 15 + "\n",
                                       "a" * 15 + "!", "é" * 16, 123, True, [], "_" * 16])
def test_exposure_lookup_bad_or_unknown_tokens_never_clean_caches(token):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    session.expires_at = 0
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(lookup_update(callback=True), token) is None
    assert (manager._sessions, manager._source_sessions) == before


@pytest.mark.parametrize("mode", ["source", "callback"])
@pytest.mark.parametrize("state, locked, retained", [
    ("pending", False, False), ("saved", False, False), ("retry", False, True),
    ("pending", True, True), ("saved", True, True),
])
def test_exposure_lookup_expiry_boundary_and_retry_retention(
    monkeypatch, mode, state, locked, retained,
):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager, state=state)
    if locked:
        with pytest.raises(StopIteration):
            session.lock.acquire().send(None)
    clock = Mock(return_value=200)
    monkeypatch.setattr(handlers_module, "time", SimpleNamespace(monotonic=clock), raising=False)
    manager._source_sessions[(1, 2, 3)] = "absent_token"
    update = lookup_update(message_id=1100 if mode == "callback" else 100,
                           callback=mode == "callback")

    found = manager._find_exposure_session(update, session.token if mode == "callback" else None)

    assert found is (session if retained else None)
    assert (session.token in manager._sessions) is retained
    assert ((ALLOWED_CHAT_ID, 42, 100) in manager._source_sessions) is retained
    assert (1, 2, 3) not in manager._source_sessions
    clock.assert_called_once_with()
    if locked:
        session.lock.release()


def test_exposure_lookup_before_expiry_and_orphan_source_are_valid_requests(monkeypatch):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    monkeypatch.setattr(handlers_module, "time", SimpleNamespace(monotonic=lambda: 199.999),
                        raising=False)
    assert manager._find_exposure_session(lookup_update()) is session
    manager._source_sessions[(ALLOWED_CHAT_ID, 42, 101)] = "missing"
    assert manager._find_exposure_session(lookup_update(message_id=101)) is None
    assert manager._source_sessions == {(ALLOWED_CHAT_ID, 42, 100): session.token}


@pytest.mark.parametrize("limit", [4, 5])
def test_exposure_lookup_new_source_evicts_only_oldest_saved_unlocked(monkeypatch, limit):
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._session_limit = limit
    pending = cache_lookup_session(manager, message_id=100, created_at=1)
    retry = cache_lookup_session(manager, message_id=101, created_at=2, state="retry")
    locked = cache_lookup_session(manager, message_id=102, created_at=3, state="saved")
    newer = cache_lookup_session(manager, message_id=103, created_at=20, state="saved")
    older = cache_lookup_session(manager, message_id=104, created_at=10, state="saved")
    with pytest.raises(StopIteration):
        locked.lock.acquire().send(None)
    monkeypatch.setattr(
        handlers_module, "time", SimpleNamespace(monotonic=lambda: 100), raising=False,
    )

    assert manager._find_exposure_session(lookup_update(message_id=999)) is None

    retained = {pending.token, retry.token, locked.token}
    if limit == 5:
        retained.add(newer.token)
    assert set(manager._sessions) == retained
    assert len(manager._source_sessions) == limit - 1
    assert older.token not in manager._source_sessions.values()
    locked.lock.release()


@pytest.mark.parametrize("mode", ["source", "callback", "new_source"])
def test_exposure_lookup_capacity_preserves_existing_replay_and_active_work(monkeypatch, mode):
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._session_limit = 1
    pending = cache_lookup_session(manager)
    saved = cache_lookup_session(manager, message_id=101, state="saved")
    monkeypatch.setattr(
        handlers_module, "time", SimpleNamespace(monotonic=lambda: 100), raising=False,
    )
    if mode == "new_source":
        # Only active sessions: capacity stays full for the future busy response.
        saved.saved = False
        expected = None
        update = lookup_update(message_id=999)
    else:
        expected = pending
        update = lookup_update(message_id=1100 if mode == "callback" else 100,
                               callback=mode == "callback")
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(
        update, pending.token if mode == "callback" else None
    ) is expected
    assert (manager._sessions, manager._source_sessions) == before


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
