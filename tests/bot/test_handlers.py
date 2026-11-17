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
from phishreport.bot.exposure import (
    CONFIRMATION_TIMEOUT_SECONDS,
    ExposureSession,
    PendingConfirmation,
)
from phishreport.bot.handlers import CHECK_CONNECTION, TelegramIOManager
from phishreport.bot.main import main
from phishreport.bot.messages import EXPOSURE_CALLBACK_PREFIX, ChatRecordBuilder, ResultFormatter
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.errors import AIUnavailable, AssessmentError, FeedbackRejected, InvalidInput
from phishreport.errors import StorageFailure as TypedStorageFailure
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345

UNAVAILABLE_EXPOSURE = (
    "This assessment is closed. Paste the message again to start a new assessment."
)
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def lookup_update(*, chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=100, callback=False):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="private"),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(message_id=message_id),
        callback_query=SimpleNamespace() if callback else None,
    )


def answer_update(action, session, *, user_id=42, message_id=None):
    result = lookup_update(
        user_id=user_id,
        message_id=session.reply_message_id if message_id is None else message_id,
        callback=True,
    )
    result.callback_query = SimpleNamespace(
        data=f"exposure:{session.token}:{action}", answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return result


def cache_lookup_session(manager, *, message_id=100, created_at=10):
    session = ExposureSession(
        {"message": "same text"}, AssessmentSnapshot(findings={}, result={"score": 0}),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=message_id,
    )
    session.created_at = created_at
    session.expires_at = 200
    session.reply_message_id = message_id + 1000
    session.saved = True
    manager._sessions[session.token] = session
    manager._source_sessions[(session.chat_id, session.user_id, message_id)] = session.token
    return session


def confirmation_update(
    pending, action, *, user_id=42, chat_id=ALLOWED_CHAT_ID, message_id=None,
):
    result = lookup_update(
        chat_id=chat_id, user_id=user_id,
        message_id=pending.card_message_id if message_id is None else message_id,
        callback=True,
    )
    result.callback_query = SimpleNamespace(
        data=f"exposure:{pending.token}:{action}", answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return result


def cache_pending_confirmation(manager, *, message_id=100, text="Verify your password now"):
    pending = PendingConfirmation(
        ChatRecordBuilder().build(text),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=message_id,
    )
    pending.card_message_id = message_id + 1000
    manager._confirmations[pending.token] = pending
    manager._confirmation_sources[
        (pending.chat_id, pending.user_id, message_id)
    ] = pending.token
    return pending


@pytest.fixture
def confirmation_setup():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager = TelegramIOManager(
        Mock(spec=DataManager), ALLOWED_CHAT_ID,
        assessment=AssessmentService(ai, LogicManager()),
    )
    return manager, cache_pending_confirmation(manager), ai


@pytest.fixture
def card_setup():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager = TelegramIOManager(
        Mock(spec=DataManager), ALLOWED_CHAT_ID,
        assessment=AssessmentService(ai, LogicManager()),
    )
    record = ChatRecordBuilder().build("Verify https://example.test invoice.pdf", sender="Sender")
    session = ExposureSession(
        record, manager._assessment.assess_with_findings(record),
        chat_id=ALLOWED_CHAT_ID, user_id=42, message_id=100,
    )
    session.commit(
        session.exposure, session.result, session.build_report(manager._assessment),
    )
    session.reply_message_id = 1100
    manager._sessions[session.token] = session
    manager._source_sessions[(ALLOWED_CHAT_ID, 42, 100)] = session.token
    manager._data_manager.save.reset_mock()
    return manager, session, ai


@pytest.mark.parametrize("action,score,exposure", [
    ("clicked", 80, {
        "clicked": True, "downloaded": None,
        "submitted_category": None, "disclosure_answered": False,
    }),
    ("password", 90, {
        "clicked": None, "downloaded": None,
        "submitted_category": "password", "disclosure_answered": True,
    }),
])
def test_exposure_answer_rescores_saves_and_edits_in_place(card_setup, action, score, exposure):
    manager, session, ai = card_setup
    incoming = answer_update(action, session)

    asyncio.run(asyncio.wait_for(manager.exposure_callback(incoming, None), 5))

    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_awaited_once()
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Priority: High" in text
    assert f"Rule-based score: {score}" in text
    assert "Rule evaluation trace" not in text
    assert session.result["score"] == score
    assert session.exposure == exposure
    assert session.saved and not session.dismissed
    manager._data_manager.save.assert_called_once()
    saved = manager._data_manager.save.call_args.args[0]
    assert saved["assessment_id"] == session.assessment_id
    assert saved["result"]["priority"] == "HIGH"
    assert saved["exposure"] == exposure
    keyboard = incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    if action == "password":
        assert keyboard is None
        assert text.endswith("\n\nSaved. Nothing more to answer.")
    else:
        assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
            ["Shared a password/OTP", "Nothing else"],
        ]
    assert ai.assess.call_count == 1


def test_nothing_happened_removes_the_keyboard_without_writing(card_setup):
    manager, session, ai = card_setup
    before = deepcopy((session.result, session.exposure, session.report))
    incoming = answer_update("nothing", session)

    asyncio.run(asyncio.wait_for(manager.exposure_callback(incoming, None), 5))

    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Rule-based score: 60" in text
    assert incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"] is None
    assert (session.result, session.exposure, session.report) == before
    assert session.dismissed and session.saved
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


def test_repeated_and_chained_answers_save_only_when_state_changes(card_setup):
    manager, session, ai = card_setup

    async def scenario():
        await manager.exposure_callback(answer_update("clicked", session), None)
        await manager.exposure_callback(answer_update("clicked", session), None)
        assert manager._data_manager.save.call_count == 1
        assert session.result["score"] == 80
        await manager.exposure_callback(answer_update("password", session), None)
        assert manager._data_manager.save.call_count == 2
        assert session.result["score"] == 90

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert ai.assess.call_count == 1


def test_password_answer_ends_the_card_and_a_repeat_saves_only_once(card_setup):
    manager, session, ai = card_setup
    first = answer_update("password", session)

    asyncio.run(asyncio.wait_for(manager.exposure_callback(first, None), 5))

    text = first.callback_query.edit_message_text.call_args.args[0]
    assert "Rule-based score: 90" in text
    assert text.endswith("\n\nSaved. Nothing more to answer.")
    assert first.callback_query.edit_message_text.call_args.kwargs["reply_markup"] is None
    manager._data_manager.save.assert_called_once()

    repeat = answer_update("password", session)
    asyncio.run(asyncio.wait_for(manager.exposure_callback(repeat, None), 5))

    repeat.callback_query.answer.assert_awaited_once_with("Already saved.")
    repeat.callback_query.edit_message_text.assert_not_awaited()
    manager._data_manager.save.assert_called_once()
    assert ai.assess.call_count == 1


def test_clicked_answer_keeps_only_the_answers_that_can_raise_the_score(card_setup):
    manager, session, ai = card_setup
    incoming = answer_update("clicked", session)

    asyncio.run(asyncio.wait_for(manager.exposure_callback(incoming, None), 5))

    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Rule-based score: 80" in text
    assert "Saved. Nothing more to answer." not in text
    keyboard = incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Shared a password/OTP", "Nothing else"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        [f"exposure:{session.token}:password", f"exposure:{session.token}:nothing"],
    ]
    manager._data_manager.save.assert_called_once()
    assert ai.assess.call_count == 1


def test_nothing_else_ends_the_clicked_card_and_keeps_the_80_report(card_setup):
    manager, session, ai = card_setup

    async def scenario():
        await manager.exposure_callback(answer_update("clicked", session), None)
        manager._data_manager.save.assert_called_once()
        clicked_report = deepcopy(manager._data_manager.save.call_args.args[0])

        incoming = answer_update("nothing", session)
        await manager.exposure_callback(incoming, None)

        text = incoming.callback_query.edit_message_text.call_args.args[0]
        assert "Rule-based score: 80" in text
        assert text.endswith("\n\nSaved. Nothing more to answer.")
        assert incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"] is None
        assert session.result["score"] == 80 and session.report["result"]["score"] == 80
        assert session.report["assessment_id"] == clicked_report["assessment_id"]
        manager._data_manager.save.assert_called_once()
        assert ai.assess.call_count == 1

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("stale_action", ["clicked", "password", "nothing"])
def test_stale_answer_after_removal_changes_nothing_and_acks(card_setup, stale_action):
    manager, session, ai = card_setup

    async def scenario():
        await manager.exposure_callback(answer_update("password", session), None)
        before = deepcopy((session.result, session.exposure, session.report))
        manager._data_manager.save.assert_called_once()

        stale = answer_update(stale_action, session)
        await manager.exposure_callback(stale, None)

        stale.callback_query.answer.assert_awaited_once_with("Already saved.")
        stale.callback_query.edit_message_text.assert_not_awaited()
        assert (session.result, session.exposure, session.report) == before
        manager._data_manager.save.assert_called_once()
        assert ai.assess.call_count == 1

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_expired_answer_acks_expiry_without_changing_the_card(card_setup):
    manager, session, ai = card_setup
    before = deepcopy((session.result, session.exposure, session.report))
    session.expires_at = 0
    incoming = answer_update("clicked", session)

    asyncio.run(asyncio.wait_for(manager.exposure_callback(incoming, None), 5))

    incoming.callback_query.answer.assert_awaited_once_with(
        "This assessment expired. Paste the message again to start a new assessment."
    )
    incoming.callback_query.edit_message_text.assert_not_awaited()
    assert (session.result, session.exposure, session.report) == before
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("case", [
    "wrong_owner", "wrong_reply", "unknown_token", "unknown_action",
    "old_downloaded", "old_finish", "old_skip", "old_retry", "newline", "prefix",
    "token_length", "none_payload", "numeric_payload",
])
def test_exposure_callback_invalid_neutral_no_work(card_setup, case):
    manager, session, ai = card_setup
    incoming = answer_update("clicked", session)
    if case == "wrong_owner":
        incoming.effective_user.id += 1
    elif case == "wrong_reply":
        incoming.effective_message.message_id += 1
    else:
        incoming.callback_query.data = {
            "unknown_token": f"exposure:{'_' * 16}:clicked",
            "unknown_action": f"exposure:{session.token}:unknown",
            "old_downloaded": f"exposure:{session.token}:downloaded",
            "old_finish": f"exposure:{session.token}:finish",
            "old_skip": f"exposure:{session.token}:skip",
            "old_retry": f"exposure:{session.token}:retry",
            "newline": f"exposure:{session.token}:clicked\n",
            "prefix": f"other:{session.token}:clicked",
            "token_length": f"exposure:{session.token}a:clicked",
            "none_payload": None, "numeric_payload": 1,
        }[case]
    before = deepcopy((session.exposure, session.result))
    asyncio.run(manager.exposure_callback(incoming, None))
    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        UNAVAILABLE_EXPOSURE, reply_markup=None,
    )
    assert (session.exposure, session.result) == before and not session.dismissed
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("case", ["no_chat", "missing_type", "group", "disallowed"])
def test_exposure_callback_disallowed_ack_only(card_setup, case):
    manager, session, _ = card_setup
    incoming = answer_update("clicked", session)
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
    assert not session.dismissed and session.exposure["clicked"] is None


@pytest.mark.parametrize("chat_id", ["absent", None, "12345", 12345.0, True, False])
def test_exposure_callback_invalid_chat_id_ack_only(card_setup, chat_id):
    manager, session, ai = card_setup
    manager._allowed_chat_id = ALLOWED_CHAT_ID
    incoming = answer_update("clicked", session)
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
    assert session.exposure["clicked"] is None and not session.dismissed
    manager._data_manager.save.assert_not_called()
    assert ai.assess.call_count == 1


def test_exposure_callback_no_query_and_failed_ack_never_lookup(card_setup):
    manager, session, _ = card_setup
    manager._find_exposure_session = Mock(side_effect=AssertionError("No lookup"))

    async def scenario():
        await manager.exposure_callback(SimpleNamespace(), None)
        incoming = answer_update("clicked", session)
        incoming.callback_query.answer.side_effect = RuntimeError("ack failed")
        with pytest.raises(RuntimeError, match="ack failed"):
            await manager.exposure_callback(incoming, None)

    asyncio.run(scenario())


def test_exposure_callback_lookup_happens_after_ack(card_setup):
    manager, session, _ = card_setup
    incoming = answer_update("clicked", session)
    original = manager._find_exposure_session

    def find(*args):
        incoming.callback_query.answer.assert_awaited_once_with()
        return original(*args)

    manager._find_exposure_session = find
    asyncio.run(manager.exposure_callback(incoming, None))


def test_confirmation_cancel_discards_without_ai_or_storage(confirmation_setup):
    manager, pending, ai = confirmation_setup
    incoming = confirmation_update(pending, "cancel")

    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "Cancelled. Nothing was sent or saved.", reply_markup=None,
    )
    ai.assess.assert_not_called()
    manager._data_manager.save.assert_not_called()
    assert manager._confirmations == {} and manager._confirmation_sources == {}
    assert manager._sessions == {} and manager._source_sessions == {}


def test_confirmation_yes_assesses_once_saves_raw_text_and_reuses_the_card(confirmation_setup):
    manager, pending, ai = confirmation_setup
    raw = pending.record["message"]
    card_id = pending.card_message_id
    incoming = confirmation_update(pending, "confirm")

    asyncio.run(manager.exposure_callback(incoming, None))

    ai.assess.assert_called_once()
    manager._data_manager.save.assert_called_once()
    saved = manager._data_manager.save.call_args.args[0]
    assert saved["schema_version"] == 3
    assert saved["message"] == raw
    assert "Check this message?" not in saved["message"]
    session, = manager._sessions.values()
    assert session.token == pending.token
    assert session.assessment_id == saved["assessment_id"]
    assert session.reply_message_id == card_id
    assert session.record["message"] == raw
    assert manager._confirmations == {} and manager._confirmation_sources == {}
    incoming.callback_query.edit_message_text.assert_awaited_once()
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Priority: Medium" in text and "Rule-based score: 60" in text
    keyboard = incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Clicked link", "Shared a password/OTP"],
        ["Nothing happened"],
    ]


def test_duplicate_confirmation_taps_run_one_assessment_and_one_save(confirmation_setup):
    manager, pending, ai = confirmation_setup
    first = confirmation_update(pending, "confirm")
    second = confirmation_update(pending, "confirm")

    async def scenario():
        await asyncio.gather(
            manager.exposure_callback(first, None),
            manager.exposure_callback(second, None),
        )

    asyncio.run(asyncio.wait_for(scenario(), 5))

    assert ai.assess.call_count == 1
    manager._data_manager.save.assert_called_once()
    session, = manager._sessions.values()
    assert session.token == pending.token and session.saved
    for incoming in (first, second):
        incoming.callback_query.answer.assert_awaited_once_with()
        incoming.callback_query.edit_message_text.assert_awaited_once()
        text = incoming.callback_query.edit_message_text.call_args.args[0]
        assert "Priority: Medium" in text and "Rule-based score: 60" in text


def test_expired_confirmation_card_never_assesses_or_saves(
    confirmation_setup, monkeypatch,
):
    manager, pending, ai = confirmation_setup
    monkeypatch.setattr(
        "phishreport.bot.exposure.time.monotonic",
        lambda: pending.created_at + CONFIRMATION_TIMEOUT_SECONDS,
    )
    incoming = confirmation_update(pending, "confirm")

    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.answer.assert_awaited_once_with()
    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "This confirmation expired. Paste the message again.", reply_markup=None,
    )
    ai.assess.assert_not_called()
    manager._data_manager.save.assert_not_called()
    assert manager._confirmations == {} and manager._confirmation_sources == {}
    assert manager._sessions == {}


@pytest.mark.parametrize("case", ["wrong_owner", "wrong_chat", "wrong_card", "missing_card"])
def test_confirmation_callback_requires_the_exact_card_owner_and_chat(
    confirmation_setup, case,
):
    manager, pending, ai = confirmation_setup
    incoming = confirmation_update(pending, "confirm")
    if case == "wrong_owner":
        incoming.effective_user.id += 1
    elif case == "wrong_chat":
        incoming.effective_chat.id += 1
    elif case == "wrong_card":
        incoming.effective_message.message_id += 1
    else:
        pending.card_message_id = None
        incoming.effective_message.message_id = pending.message_id

    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.answer.assert_awaited_once_with()
    ai.assess.assert_not_called()
    manager._data_manager.save.assert_not_called()
    assert manager._confirmations[pending.token] is pending
    assert manager._sessions == {}


def test_confirmation_without_assessment_service_stops_without_saving():
    manager = TelegramIOManager(Mock(spec=DataManager), ALLOWED_CHAT_ID)
    pending = cache_pending_confirmation(manager)
    incoming = confirmation_update(pending, "confirm")

    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "Message assessment is not available right now.", reply_markup=None,
    )
    manager._data_manager.save.assert_not_called()
    assert manager._confirmations == {} and manager._sessions == {}


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("error_type", [OSError, TypedStorageFailure])
def test_exposure_callback_save_failure_keeps_the_saved_card_and_can_retry(
    card_setup, tmp_path, backend, error_type,
):
    manager, session, ai = card_setup
    error = error_type() if issubclass(error_type, AssessmentError) else error_type("SECRET path")
    error.__cause__ = RuntimeError("SECRET private storage cause")
    manager._data_manager.save.side_effect = error

    async def scenario():
        failed = answer_update("clicked", session)
        await manager.exposure_callback(failed, None)
        text = failed.callback_query.edit_message_text.call_args.args[0]
        assert text.startswith("Could not update the assessment. Please try again.")
        assert "SECRET" not in text and "Rule-based score: 60" in text
        assert session.exposure["clicked"] is None and session.result["score"] == 60
        assert session.saved and session.report["result"]["score"] == 60

        storage = (JsonReportStorage(tmp_path / "history.json") if backend == "json"
                   else SqliteReportStorage(tmp_path / "history.sqlite3"))
        manager._data_manager = DataManager(storage)
        retry = answer_update("clicked", session)
        await manager.exposure_callback(retry, None)
        report, = manager._data_manager.load(strict=True)
        assert report["result"]["priority"] == "HIGH"
        assert report["assessment_id"] == session.assessment_id
        assert session.saved and session.result["score"] == 80

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("error", [
    OSError, ValueError, RuntimeError, AssessmentError, AIUnavailable, InvalidInput,
    FeedbackRejected,
])
def test_exposure_callback_expected_answer_failure_safe_feedback(card_setup, error):
    manager, session, _ = card_setup
    failure = error() if issubclass(error, AssessmentError) else error("SECRET")
    failure.__cause__ = RuntimeError("SECRET private scoring cause")
    manager._assessment.rescore = Mock(side_effect=failure)
    before = deepcopy((session.exposure, session.result, session.record, session.findings))
    incoming = answer_update("clicked", session)
    asyncio.run(manager.exposure_callback(incoming, None))
    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert text.startswith("Could not update the assessment. Please try again.")
    assert "SECRET" not in text and "Rule-based score: 60" in text
    assert len(text.encode("utf-16-le")) // 2 <= 4096
    assert (session.exposure, session.result, session.record, session.findings) == before
    assert session.saved and session.report["result"]["score"] == 60
    manager._data_manager.save.assert_not_called()


def test_exposure_callback_missing_service_does_not_write(card_setup):
    manager, session, _ = card_setup
    manager._assessment = None

    incoming = answer_update("clicked", session)
    asyncio.run(manager.exposure_callback(incoming, None))

    text = incoming.callback_query.edit_message_text.call_args.args[0]
    assert text.startswith("Could not update the assessment. Please try again.")
    assert session.exposure["clicked"] is None
    manager._data_manager.save.assert_not_called()


@pytest.mark.parametrize("not_modified", [False, True])
def test_exposure_callback_telegram_failure_preserves_new_revision(card_setup, not_modified):
    manager, session, ai, = card_setup

    async def scenario():
        incoming = answer_update("clicked", session)
        incoming.callback_query.edit_message_text.side_effect = BadRequest(
            "MESSAGE IS NOT MODIFIED" if not_modified else "edit unavailable",
        )
        if not_modified:
            await manager.exposure_callback(incoming, None)
        else:
            with pytest.raises(BadRequest, match="edit unavailable"):
                await manager.exposure_callback(incoming, None)
        assert session.saved and session.result["score"] == 80
        await manager.exposure_callback(answer_update("clicked", session), None)

    asyncio.run(scenario())
    manager._data_manager.save.assert_called_once()
    assert ai.assess.call_count == 1


@pytest.mark.parametrize("action", ["clicked", "password", "nothing"])
def test_exposure_callback_ack_before_lock_expiry_while_waiting(card_setup, action):
    manager, session, _ = card_setup
    incoming = answer_update(action, session)

    async def scenario():
        async with session.lock:
            task = asyncio.create_task(manager.exposure_callback(incoming, None))
            await asyncio.sleep(0)
            incoming.callback_query.answer.assert_awaited_once_with()
            assert not task.done()
            session.expires_at = 0
        await task

    asyncio.run(asyncio.wait_for(scenario(), 5))
    incoming.callback_query.edit_message_text.assert_not_awaited()
    assert session.exposure["clicked"] is None and not session.dismissed
    assert session.result["score"] == 60
    manager._data_manager.save.assert_not_called()


def test_exposure_callback_serialized_edits_preserve_current_answer(card_setup):
    manager, session, ai, = card_setup
    edits = []

    async def scenario():
        editing, release = asyncio.Event(), asyncio.Event()
        first, second = answer_update("clicked", session), answer_update("password", session)

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

    asyncio.run(asyncio.wait_for(scenario(), 8))
    assert manager._data_manager.save.call_count == 2
    assert session.result["score"] == 90
    assert "Rule-based score: 80" in edits[0]
    assert "Rule-based score: 90" in edits[1]
    assert ai.assess.call_count == 1


def test_write_report_cancellation_waits_for_the_outcome():
    manager = TelegramIOManager(Mock(spec=DataManager))
    release = threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        commits = []

        def save(report):
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise TimeoutError("Test did not release storage")

        manager._data_manager.save.side_effect = save
        task = asyncio.create_task(manager._write_report({"report": 1}, lambda: commits.append(1)))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel("first cancellation")
            await asyncio.sleep(0)
            task.cancel("second cancellation")
            await asyncio.sleep(0)
            assert not task.done() and commits == []
            assert manager.save_lock.locked()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await asyncio.wait_for(task, 3)
        assert commits == [1]
        assert not manager.save_lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 10))
    manager._data_manager.save.assert_called_once()


def test_write_report_failure_does_not_commit_and_releases_the_lock():
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._data_manager.save.side_effect = OSError("storage unavailable")
    commits = []

    async def scenario():
        with pytest.raises(OSError):
            await manager._write_report({"report": 1}, lambda: commits.append(1))
        assert not manager.save_lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    assert commits == []


def test_write_report_cancel_waiting_global_lock_never_writes():
    manager = TelegramIOManager(Mock(spec=DataManager))
    commits = []

    async def scenario():
        async with manager.save_lock:
            task = asyncio.create_task(
                manager._write_report({"report": 1}, lambda: commits.append(1))
            )
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not manager.save_lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 5))
    manager._data_manager.save.assert_not_called()
    assert commits == []


def test_write_report_cancelled_worker_does_not_spin():
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._data_manager.save.side_effect = asyncio.CancelledError("worker cancelled")
    commits = []

    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await manager._write_report({"report": 1}, lambda: commits.append(1))
        assert not manager.save_lock.locked()

    asyncio.run(asyncio.wait_for(scenario(), 3))
    assert commits == []


def test_write_report_sessions_and_gmail_share_serial_writer():
    manager = TelegramIOManager(Mock(spec=DataManager))
    release = threading.Event()
    active = peak = 0
    calls = []

    async def scenario():
        nonlocal active, peak
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
            tasks = [asyncio.create_task(manager._write_report({"channel": "chat", "n": index}))
                     for index in range(2)]
            await asyncio.sleep(0)
            assert len(calls) == 1
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(gmail, *tasks), 3)

    asyncio.run(asyncio.wait_for(scenario(), 10))
    assert peak == 1 and active == 0 and len(calls) == 3


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
@pytest.mark.parametrize("locked, retained", [(False, False), (True, True)])
def test_exposure_lookup_expiry_drops_only_unlocked_sessions(
    monkeypatch, mode, locked, retained,
):
    manager = TelegramIOManager(Mock(spec=DataManager))
    session = cache_lookup_session(manager)
    if locked:
        asyncio.run(session.lock.acquire())
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
def test_exposure_lookup_new_source_evicts_only_oldest_unlocked(monkeypatch, limit):
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._session_limit = limit
    oldest = cache_lookup_session(manager, message_id=100, created_at=1)
    middle = cache_lookup_session(manager, message_id=101, created_at=2)
    locked = cache_lookup_session(manager, message_id=102, created_at=3)
    newer = cache_lookup_session(manager, message_id=103, created_at=20)
    older = cache_lookup_session(manager, message_id=104, created_at=10)
    asyncio.run(locked.lock.acquire())
    monkeypatch.setattr(
        handlers_module, "time", SimpleNamespace(monotonic=lambda: 100), raising=False,
    )

    assert manager._find_exposure_session(lookup_update(message_id=999)) is None

    assert locked.token in manager._sessions
    assert oldest.token not in manager._sessions
    assert len(manager._sessions) == limit - 1
    assert len(manager._source_sessions) == limit - 1
    if limit == 4:
        assert middle.token not in manager._sessions
        assert newer.token in manager._sessions and older.token in manager._sessions
    else:
        assert {middle.token, newer.token, older.token} <= set(manager._sessions)
    locked.lock.release()


@pytest.mark.parametrize("mode", ["source", "callback", "new_source"])
def test_exposure_lookup_capacity_preserves_existing_replay_and_active_work(monkeypatch, mode):
    manager = TelegramIOManager(Mock(spec=DataManager))
    manager._session_limit = 1
    active = cache_lookup_session(manager)
    other = cache_lookup_session(manager, message_id=101)
    monkeypatch.setattr(
        handlers_module, "time", SimpleNamespace(monotonic=lambda: 100), raising=False,
    )
    if mode == "new_source":
        # Capacity is full of unlocked sessions, so the oldest gives way.
        expected = None
        update = lookup_update(message_id=999)
    else:
        expected = active
        update = lookup_update(message_id=1100 if mode == "callback" else 100,
                               callback=mode == "callback")
    before = (manager._sessions.copy(), manager._source_sessions.copy())

    assert manager._find_exposure_session(
        update, active.token if mode == "callback" else None
    ) is expected
    if mode == "new_source":
        assert other.token not in manager._sessions
    else:
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


@pytest.mark.parametrize("error_type", [PermissionError, TypedStorageFailure, AssessmentError])
def test_connection_check_handles_io_error_without_disclosing_details(error_type):
    data_manager = Mock(spec=DataManager)
    error = (
        error_type() if issubclass(error_type, AssessmentError) else error_type("sensitive path")
    )
    error.__cause__ = OSError("private history path")
    data_manager.load.side_effect = error
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID)
    update = fake_update()
    sequence = Mock()
    sequence.attach_mock(update.callback_query.answer, "answer")
    sequence.attach_mock(data_manager.load, "load")
    sequence.attach_mock(update.effective_message.reply_text, "reply")

    asyncio.run(manager.check_connection(update, None))

    update.callback_query.answer.assert_awaited_once_with()
    update.effective_message.reply_text.assert_awaited_once_with(
        "Could not read local history. Please try again."
    )
    data_manager.load.assert_called_once_with(strict=True)
    assert sequence.mock_calls == [
        call.answer(), call.load(strict=True),
        call.reply("Could not read local history. Please try again."),
    ]


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
    start, link, checkmail, unlink, check, feedback, exposure, text = app.handlers[0]
    assert isinstance(start, CommandHandler)
    assert start.commands == {"start"}
    assert link.commands == {"linkgmail"}
    assert checkmail.commands == {"checkmail"}
    assert unlink.commands == {"unlinkgmail"}
    assert isinstance(check, CallbackQueryHandler)
    assert check.pattern.match(CHECK_CONNECTION)
    assert not check.pattern.match(CHECK_CONNECTION + "\n")
    assert check.callback.__name__ == "check_connection"
    assert check.block
    assert isinstance(feedback, CallbackQueryHandler)
    assert feedback.pattern.match("fb:o:assessment-123")
    assert not feedback.pattern.match("other:assessment-123")
    assert isinstance(exposure, CallbackQueryHandler)
    assert exposure.callback.__self__ is check.callback.__self__
    assert exposure.callback.__name__ == "exposure_callback"
    assert exposure.pattern.pattern == rf"^{EXPOSURE_CALLBACK_PREFIX}:"
    for payload in ("exposure:bad", "exposure:bad\n", "exposure::finish"):
        assert exposure.pattern.match(payload)
        assert not check.pattern.match(payload)
    assert not exposure.pattern.match(CHECK_CONNECTION)
    assert not exposure.pattern.match(CHECK_CONNECTION + "\n")
    assert exposure.block is False
    assert isinstance(text, MessageHandler)
    assert text.callback.__name__ == "assess_message"
    assert text.block is False
    assert app.update_processor.max_concurrent_updates == 1


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
