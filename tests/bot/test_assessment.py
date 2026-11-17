"""Assess chat messages through the Telegram handler with fake updates and no live AI."""

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason
from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import (
    MAX_REPLY_CHARS,
    ChatRecordBuilder,
    ResultFormatter,
)
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.errors import (
    AIUnavailable,
    AssessmentError,
    FeedbackRejected,
    InvalidInput,
    StorageFailure,
)
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def update_with(text, chat_id=ALLOWED_CHAT_ID, chat_type="private", message_id=100):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=42),
        callback_query=None,
        effective_message=SimpleNamespace(
            text=text, message_id=message_id,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=message_id + 1000)),
        ),
    )


def build(ai_manager=None, data_manager=None, allowed_chat_id=ALLOWED_CHAT_ID):
    ai_manager = ai_manager or Mock(**{"assess.return_value": FINDINGS})
    data_manager = data_manager or Mock(spec=DataManager)
    service = AssessmentService(ai_manager, LogicManager())
    return TelegramIOManager(data_manager, allowed_chat_id, assessment=service), data_manager


def reply_text(update):
    return update.effective_message.reply_text.call_args.args[0]


def callback_with(data, chat_id=ALLOWED_CHAT_ID, chat_type="private"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        callback_query=SimpleNamespace(data=data, answer=AsyncMock()),
    )


@pytest.mark.parametrize("stage", ["lookup", "service"])
@pytest.mark.parametrize("failure_type", [StorageFailure, FeedbackRejected, AssessmentError])
def test_feedback_submit_domain_failure_preserves_pending_for_one_safe_retry(
    tmp_path, stage, failure_type,
):
    manager, data = build()
    store = FeedbackStore(tmp_path / "feedback.json")
    manager._feedback_service = Mock(wraps=FeedbackService(store))
    report = {
        "schema_version": 3, "assessment_id": "saved-assessment", "channel": "chat",
        "message": "Original message.",
        "result": {"score": 60, "priority": "MEDIUM", "reasons": ["Original reason."]},
    }
    original_report = deepcopy(report)
    data.load.return_value = [report]
    pending = {
        "assessment_id": "saved-assessment", "category": "incorrect_priority",
        "corrected_priority": "LOW",
    }
    original_pending = pending.copy()
    context = SimpleNamespace(user_data={"pending_feedback": pending, "unrelated": "keep"})
    error = failure_type()
    error.__cause__ = OSError("private history path and credential details")
    failing_boundary = data.load if stage == "lookup" else manager._feedback_service.submit
    failing_boundary.side_effect = error

    async def scenario():
        failed = update_with("Please review this priority.")
        await manager._submit_feedback(failed, context, pending, failed.effective_message.text)
        failed.effective_message.reply_text.assert_awaited_once_with(
            "Could not save your feedback. Please try again."
        )
        assert context.user_data["pending_feedback"] is pending
        assert pending == original_pending
        assert context.user_data["unrelated"] == "keep"
        assert store.load() == []
        if stage == "lookup":
            manager._feedback_service.submit.assert_not_called()

        failing_boundary.side_effect = None
        retry = update_with("Please review this priority.")
        await manager._submit_feedback(retry, context, pending, retry.effective_message.text)
        retry.effective_message.reply_text.assert_awaited_once_with(
            "Thank you. Your feedback was saved for review."
        )
        assert context.user_data == {"unrelated": "keep"}
        [feedback] = store.load()
        assert feedback.assessment_id == "saved-assessment"
        assert feedback.category == "incorrect_priority"
        assert feedback.corrected_priority == "LOW"
        assert feedback.comment == "Please review this priority."
        calls_after_retry = manager._feedback_service.submit.call_count
        replay = callback_with("fb:s:saved-assessment")
        await manager.handle_feedback_callback(replay, context)
        replay.effective_message.reply_text.assert_awaited_once_with(
            "This feedback session expired. Please start again."
        )
        assert manager._feedback_service.submit.call_count == calls_after_retry
        assert store.load() == [feedback]

    asyncio.run(scenario())
    assert report == original_report
    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "service"])
@pytest.mark.parametrize("failure_type", [TypeError, KeyError])
def test_feedback_submit_programmer_errors_surface(stage, failure_type):
    manager, data = build()
    manager._feedback_service = Mock(spec=FeedbackService)
    data.load.return_value = [{
        "schema_version": 3, "assessment_id": "saved-assessment", "channel": "chat",
        "message": "Original message.",
        "result": {"score": 60, "priority": "MEDIUM", "reasons": ["Original reason."]},
    }]
    pending = {"assessment_id": "saved-assessment", "category": "false_negative"}
    context = SimpleNamespace(user_data={"pending_feedback": pending})
    update = update_with("Review this.")
    boundary = data.load if stage == "lookup" else manager._feedback_service.submit
    boundary.side_effect = failure_type("programmer defect")

    with pytest.raises(failure_type, match="programmer defect"):
        asyncio.run(manager._submit_feedback(update, context, pending, "Review this."))

    assert context.user_data["pending_feedback"] is pending
    update.effective_message.reply_text.assert_not_called()
    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("payload", ["fb:o:saved-assessment", "fb:c:fn:saved-assessment"])
@pytest.mark.parametrize("failure_type", [StorageFailure, AssessmentError, OSError, ValueError])
@pytest.mark.parametrize("has_pending", [False, True])
def test_feedback_lookup_failures_preserve_state_without_opening_a_menu(
    payload, failure_type, has_pending,
):
    manager, data = build()
    manager._feedback_service = Mock(spec=FeedbackService)
    update = callback_with(payload)
    pending = {
        "assessment_id": "earlier-assessment", "category": "incorrect_priority",
        "corrected_priority": "HIGH",
    }
    original = {"unrelated": "keep"}
    if has_pending:
        original["pending_feedback"] = pending.copy()
    context = SimpleNamespace(user_data=original.copy())
    error = failure_type()
    error.__cause__ = OSError("private history path and credential details")

    def fail_load(*, strict):
        assert strict is True
        update.callback_query.answer.assert_awaited_once_with()
        raise error

    data.load.side_effect = fail_load

    asyncio.run(manager.handle_feedback_callback(update, context))

    expected = (
        "Could not load the assessment for feedback. Please try again."
        if issubclass(failure_type, AssessmentError)
        else "This assessment is no longer available for feedback."
    )
    update.effective_message.reply_text.assert_awaited_once_with(expected)
    data.load.assert_called_once_with(strict=True)
    assert context.user_data == original
    if has_pending:
        assert context.user_data["pending_feedback"] is original["pending_feedback"]
    manager._assessment._ai_manager.assess.assert_not_called()
    manager._feedback_service.submit.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("payload", ["fb:o:saved-assessment", "fb:c:fn:saved-assessment"])
@pytest.mark.parametrize("failure_type", [TypeError, KeyError])
def test_feedback_lookup_programmer_errors_surface(payload, failure_type):
    manager, data = build()
    manager._feedback_service = Mock(spec=FeedbackService)
    update = callback_with(payload)
    context = SimpleNamespace(user_data={"pending_feedback": {"assessment_id": "earlier"}})
    data.load.side_effect = failure_type("programmer defect")

    with pytest.raises(failure_type, match="programmer defect"):
        asyncio.run(manager.handle_feedback_callback(update, context))

    update.callback_query.answer.assert_awaited_once_with()
    update.effective_message.reply_text.assert_not_called()
    data.load.assert_called_once_with(strict=True)
    assert context.user_data == {"pending_feedback": {"assessment_id": "earlier"}}
    manager._assessment._ai_manager.assess.assert_not_called()
    manager._feedback_service.submit.assert_not_called()


@pytest.mark.parametrize("with_trace", [False, True])
def test_saved_assessment_lookup_returns_an_independent_unchanged_result(with_trace):
    saved_result = {
        "score": 60,
        "priority": "MEDIUM",
        "reasons": ["Original reason."],
        "checklist": ["Original action."],
    }
    if with_trace:
        saved_result.update({
            "matched_rule": "SuspiciousCredentialRule",
            "trace": [{"rule_name": "SuspiciousCredentialRule", "matched": True, "score": 60}],
        })
    source = {
        "schema_version": 3,
        "assessment_id": "saved-assessment",
        "channel": "chat",
        "message": "Original message.",
        "result": saved_result,
    }
    manager, data = build()
    data.load.return_value = [source]

    result = manager._load_assessment_result("saved-assessment")

    expected = {
        "assessment_id": "saved-assessment",
        "score": 60,
        "priority": "MEDIUM",
        "reasons": ["Original reason."],
        "checklist": ["Original action."],
    }
    if with_trace:
        expected.update({
            "matched_rule": "SuspiciousCredentialRule",
            "trace": [{"rule_name": "SuspiciousCredentialRule", "matched": True, "score": 60}],
        })
    assert result == expected
    saved_result["reasons"].append("Later source change.")
    assert result == expected
    result["checklist"].append("Later returned change.")
    assert saved_result["checklist"] == ["Original action."]
    if with_trace:
        saved_result["trace"][0]["score"] = 90
        assert result["trace"][0]["score"] == 60
        result["trace"][0]["matched"] = False
        assert saved_result["trace"][0]["matched"] is True
    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()


@pytest.mark.parametrize("reports", [
    [],
    [{"schema_version": 3, "assessment_id": "another-assessment", "result": {}}],
    [{"schema_version": 3, "result": {}}],
    [{"schema_version": 2, "assessment_id": "saved-assessment", "result": {}}],
    [{"assessment_id": "saved-assessment", "result": {}}],
])
def test_saved_assessment_lookup_rejects_missing_or_legacy_reports(reports):
    manager, data = build()
    data.load.return_value = reports

    with pytest.raises(ValueError, match="Assessment was not found"):
        manager._load_assessment_result("saved-assessment")


def test_saved_assessment_lookup_propagates_strict_history_errors(tmp_path):
    path = tmp_path / "reports.json"
    path.write_text("invalid JSON", encoding="utf-8")
    manager, _ = build(data_manager=DataManager(JsonReportStorage(path)))

    with pytest.raises(StorageFailure) as caught:
        manager._load_assessment_result("saved-assessment")
    assert isinstance(caught.value.__cause__, ValueError)
    assert str(caught.value) == StorageFailure.user_message


def confirmation_callback(pending, action, *, message_id=None):
    update = update_with(
        None,
        message_id=pending.card_message_id if message_id is None else message_id,
    )
    update.callback_query = SimpleNamespace(
        data=f"exposure:{pending.token}:{action}",
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    return update


def confirm_pasted(manager, update):
    """Send text, accept the card the bot replied with, and return its callback."""
    asyncio.run(manager.assess_message(update, None))
    pending, = manager._confirmations.values()
    incoming = confirmation_callback(pending, "confirm")
    asyncio.run(manager.exposure_callback(incoming, None))
    return incoming


def test_text_alone_waits_for_confirmation_with_no_ai_call_or_saved_report():
    manager, data = build()
    update = update_with("Verify your password now")

    asyncio.run(manager.assess_message(update, None))

    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()
    assert manager._sessions == {} and manager._source_sessions == {}
    pending, = manager._confirmations.values()
    assert pending.record["message"] == "Verify your password now"
    assert reply_text(update) == (
        "Check this message?\n\n"
        '"Verify your password now"\n\n'
        "This text is sent to the AI provider for analysis."
    )
    keyboard = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Yes, check it", "Cancel"],
    ]
    assert [
        [button.callback_data for button in row] for row in keyboard.inline_keyboard
    ] == [[f"exposure:{pending.token}:confirm", f"exposure:{pending.token}:cancel"]]


def test_confirmation_runs_one_assessment_and_saves_only_the_pasted_text():
    manager, data = build()
    update = update_with("Verify your password now")
    asyncio.run(manager.assess_message(update, None))
    pending, = manager._confirmations.values()
    card_id = pending.card_message_id

    incoming = confirmation_callback(pending, "confirm")
    asyncio.run(manager.exposure_callback(incoming, None))

    manager._assessment._ai_manager.assess.assert_called_once()
    data.save.assert_called_once()
    report = data.save.call_args.args[0]
    assert report["message"] == "Verify your password now"
    assert '"Verify your password now"' not in report["message"]
    assert "Check this message?" not in report["message"]
    session, = manager._sessions.values()
    assert session.record["message"] == "Verify your password now"
    assert session.reply_message_id == card_id
    assert pending.token not in manager._confirmations
    incoming.callback_query.edit_message_text.assert_awaited_once()
    rendered = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Priority: Medium" in rendered
    assert "Rule-based score: 60" in rendered
    keyboard = incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Clicked link", "Shared a password/OTP"],
        ["Nothing happened"],
    ]
    # The confirmation card is replaced in place, never duplicated in the chat.
    update.effective_message.reply_text.assert_awaited_once()


def test_cancel_discards_the_message_without_ai_or_storage():
    manager, data = build()
    update = update_with("Verify your password now")
    asyncio.run(manager.assess_message(update, None))
    pending, = manager._confirmations.values()

    incoming = confirmation_callback(pending, "cancel")
    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "Cancelled. Nothing was sent or saved.", reply_markup=None,
    )
    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()
    assert manager._sessions == {} and manager._source_sessions == {}
    assert manager._confirmations == {} and manager._confirmation_sources == {}


def test_expired_confirmation_never_assesses_or_saves():
    manager, data = build()
    update = update_with("Verify your password now")
    asyncio.run(manager.assess_message(update, None))
    pending, = manager._confirmations.values()
    pending.expires_at = 0

    incoming = confirmation_callback(pending, "confirm")
    asyncio.run(manager.exposure_callback(incoming, None))

    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "This confirmation expired. Paste the message again.", reply_markup=None,
    )
    manager._assessment._ai_manager.assess.assert_not_called()
    data.save.assert_not_called()
    assert manager._sessions == {} and manager._source_sessions == {}
    assert manager._confirmations == {} and manager._confirmation_sources == {}


def test_long_message_preview_is_trimmed_but_the_saved_report_keeps_all_text():
    text = "A" * 450
    manager, data = build()
    update = update_with(text)

    asyncio.run(manager.assess_message(update, None))

    preview = text[:400] + "..."
    assert reply_text(update) == (
        f'Check this message?\n\n"{preview}"\n\n'
        "This text is sent to the AI provider for analysis."
    )
    pending, = manager._confirmations.values()
    incoming = confirmation_callback(pending, "confirm")
    asyncio.run(manager.exposure_callback(incoming, None))

    report = data.save.call_args.args[0]
    assert report["message"] == text
    assert len(report["message"]) == 450
    assert report["message"].endswith("AAAA")
    assert "Check this message?" not in report["message"]


def test_a_pasted_message_shows_the_compact_saved_card():
    manager, data_manager = build()
    update = update_with("Verify your password now")

    incoming = confirm_pasted(manager, update)

    reply = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "Priority: Medium" in reply
    assert "Rule-based score: 60" in reply
    assert "Matched rule: SuspiciousCredentialRule" in reply
    assert "Reasons:" in reply and "Recommended actions:" in reply
    assert "Rule evaluation trace" not in reply
    assert "Provisional assessment" not in reply
    assert "expire" not in reply.lower() and "30 minutes" not in reply
    assert ResultFormatter.FOOTER not in reply
    data_manager.save.assert_called_once()
    session, = manager._sessions.values()
    assert session.record["message"] == "Verify your password now"
    assert session.reply_message_id == 1100
    keyboard = incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Clicked link", "Shared a password/OTP"],
        ["Nothing happened"],
    ]


async def assess_confirmed(manager, message_text, context=None):
    update = update_with(message_text)
    await manager.assess_message(update, context)
    pending, = manager._confirmations.values()
    await manager.exposure_callback(confirmation_callback(pending, "confirm"), context)
    return update


def test_telegram_feedback_flow_saves_a_comment_for_the_original_assessment(tmp_path):
    async def run_flow():
        ai_manager = Mock(**{"assess.return_value": FINDINGS})
        data_manager = DataManager(JsonReportStorage(tmp_path / "reports.json"))
        feedback_store = FeedbackStore(tmp_path / "feedback.json")
        service = AssessmentService(ai_manager, LogicManager())
        manager = TelegramIOManager(
            data_manager,
            ALLOWED_CHAT_ID,
            assessment=service,
            feedback_service=FeedbackService(feedback_store),
        )
        context = SimpleNamespace(user_data={})
        await assess_confirmed(manager, "Verify your password now", context)

        report, = data_manager.load(strict=True)
        assessment_id = report["assessment_id"]
        assert report["result"]["priority"] == "MEDIUM"

        await manager.handle_feedback_callback(callback_with(f"fb:o:{assessment_id}"), context)
        await manager.handle_feedback_callback(
            callback_with(f"fb:c:fn:{assessment_id}"), context
        )
        await manager.assess_message(update_with("The message impersonated my bank."), context)

        [feedback] = feedback_store.load()
        assert feedback.assessment_id == assessment_id
        assert feedback.category == "false_negative"
        assert feedback.comment == "The message impersonated my bank."
        assert feedback.assessment_score == report["result"]["score"]
        assert "message" not in feedback.to_dict()
        assert data_manager.load(strict=True) == [report]
        ai_manager.assess.assert_called_once()

    asyncio.run(run_flow())


def test_telegram_feedback_can_submit_a_corrected_priority_without_comment(tmp_path):
    async def run_flow():
        ai_manager = Mock(**{"assess.return_value": FINDINGS})
        data_manager = DataManager(JsonReportStorage(tmp_path / "reports.json"))
        feedback_store = FeedbackStore(tmp_path / "feedback.json")
        manager = TelegramIOManager(
            data_manager,
            ALLOWED_CHAT_ID,
            assessment=AssessmentService(ai_manager, LogicManager()),
            feedback_service=FeedbackService(feedback_store),
        )
        context = SimpleNamespace(user_data={})
        await assess_confirmed(manager, "Verify your password now", context)
        assessment_id = data_manager.load(strict=True)[0]["assessment_id"]

        await manager.handle_feedback_callback(callback_with(f"fb:o:{assessment_id}"), context)
        await manager.handle_feedback_callback(
            callback_with(f"fb:c:ip:{assessment_id}"), context
        )
        await manager.handle_feedback_callback(
            callback_with(f"fb:p:L:{assessment_id}"), context
        )
        await manager.handle_feedback_callback(callback_with(f"fb:s:{assessment_id}"), context)

        [feedback] = feedback_store.load()
        assert feedback.category == "incorrect_priority"
        assert feedback.corrected_priority == "LOW"
        assert feedback.comment is None
        assert data_manager.load(strict=True)[0]["result"]["priority"] == "MEDIUM"
        assert context.user_data == {}

    asyncio.run(run_flow())


@pytest.mark.parametrize(
    "update",
    [
        update_with("hello", chat_id=999),
        update_with("hello", chat_type="group"),
        update_with(None),
        update_with(""),
    ],
    ids=["other-chat", "group", "no-text", "empty-text"],
)
def test_messages_from_other_chats_or_without_text_are_ignored(update):
    ai_manager = Mock()
    manager, data_manager = build(ai_manager)

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_not_called()
    ai_manager.assess.assert_not_called()
    data_manager.save.assert_not_called()


def test_any_private_chat_is_served_when_no_chat_is_configured():
    manager, _ = build(allowed_chat_id=None)
    update = update_with("hello", chat_id=777)

    asyncio.run(manager.assess_message(update, None))

    assert "Check this message?" in reply_text(update)


def test_without_an_assessment_service_the_bot_says_so():
    manager = TelegramIOManager(Mock(spec=DataManager), ALLOWED_CHAT_ID)
    update = update_with("hello")

    asyncio.run(manager.assess_message(update, None))

    assert reply_text(update) == "Message assessment is not available right now."


def test_an_ai_service_failure_gets_the_friendly_message_and_nothing_is_saved():
    error = AIUnavailable()
    error.__cause__ = ProviderFailure(ProviderFailureReason.HTTP, status_code=429)
    ai_manager = Mock(**{"assess.side_effect": error})
    manager, data_manager = build(ai_manager)
    update = update_with("hello")

    incoming = confirm_pasted(manager, update)

    rendered = incoming.callback_query.edit_message_text.call_args.args[0]
    assert "rate limited" in rendered
    assert incoming.callback_query.edit_message_text.call_args.kwargs["reply_markup"] is None
    data_manager.save.assert_not_called()
    assert manager._sessions == {} and manager._confirmations == {}


def test_an_invalid_ai_reply_is_reported_and_nothing_is_saved():
    ai_manager = Mock(**{"assess.side_effect": InvalidInput()})
    manager, data_manager = build(ai_manager)
    update = update_with("hello")

    incoming = confirm_pasted(manager, update)

    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "Invalid input. Please revise it and try again.", reply_markup=None,
    )
    data_manager.save.assert_not_called()
    assert manager._sessions == {} and manager._confirmations == {}


def callback_for(session, action):
    update = update_with(None, message_id=session.reply_message_id)
    update.callback_query = SimpleNamespace(
        data=f"exposure:{session.token}:{action}",
        answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return update


def test_a_paste_save_failure_is_reported_and_leaves_no_session():
    manager, data = build()
    data.save.side_effect = OSError("disk full")
    update = update_with("hello")

    incoming = confirm_pasted(manager, update)

    incoming.callback_query.edit_message_text.assert_awaited_once_with(
        "Could not save the report. Please try again.", reply_markup=None,
    )
    assert manager._sessions == {} and manager._source_sessions == {}
    assert manager._confirmations == {} and manager._confirmation_sources == {}
    data.save.assert_called_once()
    manager._assessment._ai_manager.assess.assert_called_once()


def test_the_blocking_ai_call_runs_off_the_event_loop_thread():
    seen = {}

    def assess(record):
        seen["thread"] = threading.current_thread()
        return FINDINGS

    manager, _ = build(Mock(assess=assess))

    asyncio.run(manager.assess_message(update_with("hello"), None))
    pending, = manager._confirmations.values()
    asyncio.run(
        manager.exposure_callback(confirmation_callback(pending, "confirm"), None)
    )

    assert seen["thread"] is not threading.main_thread()


@pytest.mark.parametrize("action,score", [("clicked", 80), ("password", 90), ("nothing", 60)])
@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_paste_saves_a_medium_revision_before_any_follow_up_answer(
    tmp_path, backend, action, score,
):
    storage = (JsonReportStorage(tmp_path / "reports.json") if backend == "json"
               else SqliteReportStorage(tmp_path / "reports.sqlite3"))
    data = DataManager(storage)
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai, data)
    source = "Verify https://example.test/login and open invoice.pdf"

    async def scenario():
        update = update_with(source)
        await manager.assess_message(update, None)
        assert data.load(strict=True) == [] and not manager._sessions
        pending, = manager._confirmations.values()
        await manager.exposure_callback(confirmation_callback(pending, "confirm"), None)
        initial, = data.load(strict=True)
        assert initial["schema_version"] == 3
        assert initial["assessment_id"]
        assert initial["message"] == source
        assert initial["link"] == "https://example.test/login"
        assert initial["file_name"] == "invoice.pdf"
        assert initial["result"]["score"] == 60
        assert initial["result"]["priority"] == "MEDIUM"
        assert initial["exposure"] == {
            "clicked": None, "downloaded": None,
            "submitted_category": None, "disclosure_answered": False,
        }

        session, = manager._sessions.values()
        incoming = callback_for(session, action)
        await manager.exposure_callback(incoming, None)
        if action == "nothing":
            assert data.load(strict=True) == [initial]
            assert incoming.callback_query.edit_message_text.call_args.kwargs[
                "reply_markup"
            ] is None
        else:
            revision, = data.load(strict=True)[1:]
            assert revision["assessment_id"] == initial["assessment_id"]
            assert revision["result"]["score"] == score
            assert revision["result"]["priority"] == "HIGH"
            expected = {
                "clicked": True if action == "clicked" else None,
                "downloaded": None,
                "submitted_category": "password" if action == "password" else None,
                "disclosure_answered": action == "password",
            }
            assert revision["exposure"] == expected

    asyncio.run(scenario())
    ai.assess.assert_called_once()


@pytest.mark.parametrize("concurrent", [False, True])
def test_duplicate_source_deliveries_show_one_card_before_assessment(concurrent):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, data = build(ai)
    first, replay = update_with("hello"), update_with("hello")

    async def scenario():
        if concurrent:
            await asyncio.gather(manager.assess_message(first, None),
                                 manager.assess_message(replay, None))
        else:
            await manager.assess_message(first, None)
            await manager.assess_message(replay, None)
        assert ai.assess.call_count == 0 and data.save.call_count == 0
        assert (first.effective_message.reply_text.await_count
                + replay.effective_message.reply_text.await_count) == 1
        assert len(manager._confirmations) == 1
        pending, = manager._confirmations.values()
        await manager.exposure_callback(confirmation_callback(pending, "confirm"), None)
        # A late replay of the source must not assess or reply again.
        await manager.assess_message(replay, None)
        assert ai.assess.call_count == 1 and data.save.call_count == 1
        assert len(manager._sessions) == 1

    asyncio.run(scenario())


def test_equal_text_distinct_sources_are_independent_and_capacity_is_bounded():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, data = build(ai)
    manager._session_limit = 2

    async def scenario():
        await asyncio.gather(*(manager.assess_message(update_with("same", message_id=i), None)
                               for i in (100, 101)))
        assert len(manager._confirmations) == 2
        assert ai.assess.call_count == 0 and data.save.call_count == 0
        oldest = min(manager._confirmations.values(), key=lambda item: item.created_at)
        newest = max(manager._confirmations.values(), key=lambda item: item.created_at)
        async with oldest.lock, newest.lock:
            busy = update_with("same", message_id=102)
            await manager.assess_message(busy, None)
            assert reply_text(busy) == (
                "Too many recent assessments. Please try again shortly."
            )
        assert ai.assess.call_count == 0
        await manager.assess_message(busy, None)
        assert oldest.token not in manager._confirmations
        assert len(manager._confirmations) == 2
        assert manager._confirmation_sources[(ALLOWED_CHAT_ID, 42, 102)] in (
            manager._confirmations
        )
        for pending in list(manager._confirmations.values()):
            await manager.exposure_callback(
                confirmation_callback(pending, "confirm"), None,
            )
        assert ai.assess.call_count == 2 and data.save.call_count == 2
        assert len(manager._sessions) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["error", "cancel", "missing_id", "bool_id"])
def test_failed_confirmation_delivery_sends_a_usable_card_on_retry(failure):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, data = build(ai)
    incoming = update_with("hello")
    reply = incoming.effective_message.reply_text
    if failure in {"error", "cancel"}:
        reply.side_effect = (
            OSError("Telegram unavailable") if failure == "error" else asyncio.CancelledError()
        )
    else:
        reply.return_value = (
            SimpleNamespace() if failure == "missing_id" else SimpleNamespace(message_id=True)
        )

    async def scenario():
        if failure in {"error", "cancel"}:
            with pytest.raises(OSError if failure == "error" else asyncio.CancelledError):
                await manager.assess_message(incoming, None)
        else:
            await manager.assess_message(incoming, None)
        assert manager._confirmations == {} and manager._confirmation_sources == {}
        retry = update_with("hello")
        await manager.assess_message(retry, None)
        pending, = manager._confirmations.values()
        assert pending.card_message_id == 1100
        assert len(manager._confirmations) == 1
        assert ai.assess.call_count == 0 and data.save.call_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["effective_chat", "effective_user", "effective_message"])
@pytest.mark.parametrize("value", [None, True, "12345", 1.0])
def test_malformed_identity_is_ignored_before_authorization(field, value):
    manager, data = build()
    update = update_with("hello")
    setattr(getattr(update, field), "message_id" if field == "effective_message" else "id", value)
    manager.is_allowed = Mock(side_effect=AssertionError("Malformed update reached authorization"))
    asyncio.run(manager.assess_message(update, None))
    update.effective_message.reply_text.assert_not_called()
    assert not manager._sessions and not manager._source_sessions
    data.save.assert_not_called()


@pytest.mark.parametrize("case", [
    "missing_chat", "missing_user", "missing_message", "callback", "integer_text", "whitespace",
])
def test_malformed_envelopes_are_ignored(case):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai)
    update = update_with("hello")
    reply = update.effective_message.reply_text
    if case.startswith("missing_"):
        delattr(update, "effective_" + case.removeprefix("missing_"))
    elif case == "callback":
        update.callback_query = SimpleNamespace()
    else:
        update.effective_message.text = 123 if case == "integer_text" else "   "
    asyncio.run(manager.assess_message(update, None))
    reply.assert_not_called()
    ai.assess.assert_not_called()
    assert not manager._sessions


def test_colliding_token_is_regenerated_without_overwriting_existing_confirmation(monkeypatch):
    manager, _ = build()

    async def scenario():
        await manager.assess_message(update_with("first"), None)
        first, = manager._confirmations.values()
        tokens = iter([first.token, "A" * 16])
        monkeypatch.setattr(
            "phishreport.bot.exposure.secrets.token_urlsafe", lambda size: next(tokens),
        )
        await manager.assess_message(update_with("second", message_id=101), None)
        assert manager._confirmations[first.token] is first
        assert len(manager._confirmations) == 2
        second = manager._confirmations["A" * 16]
        assert second.record["message"] == "second"
        assert manager._confirmation_sources[(ALLOWED_CHAT_ID, 42, 101)] == second.token

    asyncio.run(scenario())


def test_expired_confirmation_source_gets_a_fresh_card():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai)

    async def scenario():
        await manager.assess_message(update_with("hello"), None)
        old, = manager._confirmations.values()
        old.expires_at = 0
        retry = update_with("hello")
        await manager.assess_message(retry, None)
        assert old.token not in manager._confirmations
        assert len(manager._confirmations) == 1
        assert "Check this message?" in reply_text(retry)

    asyncio.run(scenario())
    ai.assess.assert_not_called()


def test_a_slow_save_serializes_reports_without_losing_a_message():
    started, release = threading.Event(), threading.Event()
    reports = []

    def save(report):
        if not reports:
            started.set()
            assert release.wait(5)
        reports.append(report)

    manager, data = build()
    data.save.side_effect = save

    async def scenario():
        await manager.assess_message(update_with("first"), None)
        first, = manager._confirmations.values()
        await manager.assess_message(update_with("second", message_id=101), None)
        second = next(item for item in manager._confirmations.values() if item is not first)
        first_task = asyncio.create_task(
            manager.exposure_callback(confirmation_callback(first, "confirm"), None)
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            second_task = asyncio.create_task(
                manager.exposure_callback(confirmation_callback(second, "confirm"), None)
            )
            await asyncio.sleep(0)
            assert not second_task.done()
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), 5)
        assert len(reports) == 2
        assert {report["message"] for report in reports} == {"first", "second"}
        # A duplicate source delivery after the saves adds neither card nor report.
        await manager.assess_message(update_with("first"), None)
        assert len(reports) == 2

    asyncio.run(asyncio.wait_for(scenario(), 8))


# --- Helpers ------------------------------------------------------------------------------


def test_chat_record_builder_makes_a_record_the_logic_manager_accepts():
    record = ChatRecordBuilder().build("Verify your password now")

    LogicManager().validate_record(record)
    assert record["channel"] == "chat"
    assert (record["clicked"], record["downloaded"], record["submitted_category"]) == (
        False,
        False,
        None,
    )


@pytest.mark.parametrize(
    "text, expected_link",
    [
        ("Visit http://example.test/reset", "http://example.test/reset"),
        ("Open https://example.test/a?token=abc&next=%2Fhome.",
         "https://example.test/a?token=abc&next=%2Fhome"),
        ("Use www.example.test/login?code=123!", "www.example.test/login?code=123"),
        ("See (https://example.test/wiki/Example_(topic)).",
         "https://example.test/wiki/Example_(topic)"),
        ("See https://example.test/a_(b_(c)).", "https://example.test/a_(b_(c))"),
        ("First www.first.test/a, then https://second.test/b", "www.first.test/a"),
        ('Open <HTTPS://Example.test/Path?q=One>; now', "HTTPS://Example.test/Path?q=One"),
        ("See [https://example.test/path?q=a,b#section].", "https://example.test/path?q=a,b#section"),
        ("See https://example.test/list[0].", "https://example.test/list[0]"),
        ("See {https://example.test/{item}}.", "https://example.test/{item}"),
        ("Email user@www.example.test or user@example.test", None),
        ("Email user@sub.www.example.com", None),
        ("Email john.www.example.com@example.net", None),
        ("prefixhttps://example.test is ordinary text", None),
        ("An ordinary message without a link", None),
        ("", None),
    ],
)
def test_chat_record_builder_extracts_first_url_without_changing_source(text, expected_link):
    record = ChatRecordBuilder().build(text, sender=" Original Sender ")

    assert record["link"] == expected_link
    assert record["has_link"] is (expected_link is not None)
    assert record["message"] == text
    assert record["sender"] == " Original Sender "
    if text:
        LogicManager().validate_record(record)


@pytest.mark.parametrize(
    "filename",
    ["invoice.pdf", "letter.doc", "letter.docx", "sheet.xls", "sheet.xlsx",
     "archive.zip", "app.apk", "setup.exe", "photo.jpg", "photo.jpeg",
     "photo.png", "animation.gif", "scan.webp"],
)
def test_chat_record_builder_recognizes_supported_filenames(filename):
    record = ChatRecordBuilder().build(f'Please open "{filename}".')

    assert record["has_file"] is True
    assert record["file_name"] == filename


@pytest.mark.parametrize(
    "text, has_file, filename",
    [
        ("Open Invoice-2026.PDF, then second.zip.", True, "Invoice-2026.PDF"),
        ("Please see the attached file.", True, None),
        ("I attached a document for review.", True, None),
        ("See the attachment below.", True, None),
        ("Email invoice.pdf@example.test", False, None),
        ("Email user@example.pdf", False, None),
        ("Visit https://example.pdf/invoice.pdf?name=setup.exe", False, None),
        ("Visit www.example.pdf/download", False, None),
        ("Visit https://example.test/file.pdf then open real.docx.", True, "real.docx"),
        ("The filename is script.unknown and no file was provided.", False, None),
        ("I feel attached to this project.", False, None),
        ("Please file a report.", False, None),
        ("Look at photo.jpg.example or invoice.pdfx", False, None),
    ],
)
def test_chat_record_builder_distinguishes_files_from_email_and_url(text, has_file, filename):
    record = ChatRecordBuilder().build(text)

    assert record["has_file"] is has_file
    assert record["file_name"] == filename


def test_chat_record_builder_never_infers_exposure_from_message_claims():
    record = ChatRecordBuilder().build(
        "I clicked https://example.test, downloaded invoice.pdf and submitted my password and OTP."
    )

    assert record["clicked"] is False
    assert record["downloaded"] is False
    assert record["submitted_category"] is None
    service = AssessmentService(Mock(**{"assess.return_value": FINDINGS}), LogicManager())
    assert service.assess(record)["score"] == 60


def test_result_formatter_keeps_long_results_within_the_chat_limit():
    result = {"priority": "HIGH", "score": 90, "reasons": ["x" * 6000], "checklist": ["Act."]}

    text = ResultFormatter().format(result)

    assert len(text) <= MAX_REPLY_CHARS + len(ResultFormatter.FOOTER) + 2
    assert text.endswith(ResultFormatter.FOOTER)


def test_telegram_assessment_renders_the_rule_trace():
    result = {
        "priority": "HIGH",
        "score": 80,
        "matched_rule": "SuspiciousInteractionRule",
        "trace": [
            {"rule_name": "DisclosureRule", "matched": False, "score": None},
            {"rule_name": "SuspiciousInteractionRule", "matched": True, "score": 80},
        ],
    }

    text = ResultFormatter().format(result)

    assert "Matched rule: SuspiciousInteractionRule" in text
    assert "DisclosureRule: not matched" in text
    assert "SuspiciousInteractionRule: matched (score: 80)" in text
