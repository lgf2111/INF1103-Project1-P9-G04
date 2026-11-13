"""Assess chat messages through the Telegram handler with fake updates and no live AI."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import (
    MAX_REPLY_CHARS,
    BufferTerminal,
    ChatRecordBuilder,
    ResultFormatter,
)
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
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


def test_a_text_message_gets_provisional_questions_without_initial_save():
    manager, data_manager = build()
    update = update_with("Verify your password now")

    asyncio.run(manager.assess_message(update, None))

    reply = reply_text(update)
    assert "Priority: Medium" in reply
    assert "Rule-based score: 60" in reply
    assert "Matched rule: SuspiciousCredentialRule" in reply
    assert "Rule evaluation trace:" in reply
    assert "SuspiciousCredentialRule: matched (score: 60)" in reply
    assert reply.endswith(ResultFormatter.FOOTER)
    assert "Provisional assessment" in reply
    assert "Did you click the link / download the file?" in reply
    assert "Did you enter a password or code?" in reply
    assert "Exposure unconfirmed" in reply
    data_manager.save.assert_not_called()
    data_manager.load.assert_not_called()
    session, = manager._sessions.values()
    assert session.record["message"] == "Verify your password now"
    assert session.reply_message_id == 1100
    assert update.effective_message.reply_text.call_args.kwargs["reply_markup"] is not None



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

    assert "Priority:" in reply_text(update)


def test_without_an_assessment_service_the_bot_says_so():
    manager = TelegramIOManager(Mock(spec=DataManager), ALLOWED_CHAT_ID)
    update = update_with("hello")

    asyncio.run(manager.assess_message(update, None))

    assert reply_text(update) == "Message assessment is not available right now."


def test_an_ai_service_failure_gets_the_friendly_message_and_nothing_is_saved():
    ai_manager = Mock(**{"assess.side_effect": RuntimeError("HTTP 429")})
    manager, data_manager = build(ai_manager)
    update = update_with("hello")

    asyncio.run(manager.assess_message(update, None))

    assert "rate limited" in reply_text(update)
    data_manager.save.assert_not_called()


def test_an_invalid_ai_reply_is_reported_and_nothing_is_saved():
    ai_manager = Mock(**{"assess.side_effect": ValueError("AI response is not valid JSON")})
    manager, data_manager = build(ai_manager)
    update = update_with("hello")

    asyncio.run(manager.assess_message(update, None))

    assert reply_text(update) == "Sorry, the check failed: AI response is not valid JSON"
    data_manager.save.assert_not_called()


def callback_for(session, action):
    update = update_with(None, message_id=session.reply_message_id)
    update.callback_query = SimpleNamespace(
        data=f"exposure:{session.token}:{action}",
        answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return update


def test_a_final_save_failure_can_retry_without_reassessing():
    manager, data = build()
    data.save.side_effect = OSError("disk full")

    async def scenario():
        await manager.assess_message(update_with("hello"), None)
        session, = manager._sessions.values()
        await manager.exposure_callback(callback_for(session, "finish"), None)
        assert session.completed and not session.saved
        data.save.side_effect = None
        await manager.exposure_callback(callback_for(session, "retry"), None)
        assert session.saved
        assert data.save.call_count == 2
        assert data.save.call_args.args[0]["schema_version"] == 3

    asyncio.run(scenario())
    assert manager._assessment._ai_manager.assess.call_count == 1


def test_the_blocking_ai_call_runs_off_the_event_loop_thread():
    seen = {}

    def assess(record):
        seen["thread"] = threading.current_thread()
        return FINDINGS

    manager, _ = build(Mock(assess=assess))

    asyncio.run(manager.assess_message(update_with("hello"), None))

    assert seen["thread"] is not threading.main_thread()


@pytest.mark.parametrize("action,score", [("clicked", 80), ("downloaded", 80),
                                         ("password", 90), ("otp", 90), ("skip", 60)])
@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_initial_to_final_real_storage_keeps_answers_and_metadata(tmp_path, backend, action, score):
    storage = (JsonReportStorage(tmp_path / "reports.json") if backend == "json"
               else SqliteReportStorage(tmp_path / "reports.sqlite3"))
    data = DataManager(storage)
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai, data)
    source = "Verify https://example.test/login and open invoice.pdf"

    async def scenario():
        await manager.assess_message(update_with(source), None)
        assert data.load(strict=True) == []
        session, = manager._sessions.values()
        await manager.exposure_callback(callback_for(session, action), None)
        await manager.exposure_callback(callback_for(session, "finish"), None)
        await manager.exposure_callback(callback_for(session, "skip"), None)
        report, = data.load(strict=True)
        assert report["schema_version"] == 3
        assert report["message"] == source
        assert report["link"] == "https://example.test/login"
        assert report["file_name"] == "invoice.pdf"
        assert report["result"]["score"] == score
        assert report["result"]["priority"] == ("HIGH" if score >= 80 else "MEDIUM")
        assert report["exposure"] == {
            "clicked": True if action == "clicked" else False if action == "downloaded" else None,
            "downloaded": (
                True if action == "downloaded" else False if action == "clicked" else None
            ),
            "submitted_category": action if action in {"password", "otp"} else None,
            "disclosure_answered": action in {"password", "otp"},
        }

    asyncio.run(scenario())
    ai.assess.assert_called_once()


@pytest.mark.parametrize("concurrent", [False, True])
def test_duplicate_source_deliveries_assess_and_reply_once(concurrent):
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

    asyncio.run(scenario())
    ai.assess.assert_called_once()
    assert (first.effective_message.reply_text.await_count
            + replay.effective_message.reply_text.await_count) == 1
    assert len(manager._sessions) == 1
    data.save.assert_not_called()


def test_equal_text_distinct_sources_are_independent_and_capacity_is_bounded():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai)
    manager._session_limit = 2

    async def scenario():
        await asyncio.gather(*(manager.assess_message(update_with("same", message_id=i), None)
                               for i in (100, 101)))
        assert len(manager._sessions) == 2
        busy = update_with("same", message_id=102)
        await manager.assess_message(busy, None)
        assert reply_text(busy) == (
            "Too many pending assessments. Finish or skip an earlier one, then try again."
        )
        assert ai.assess.call_count == 2
        oldest = min(manager._sessions.values(), key=lambda s: s.created_at)
        await manager.exposure_callback(callback_for(oldest, "skip"), None)
        await manager.assess_message(busy, None)
        assert oldest.token not in manager._sessions
        assert len(manager._sessions) == 2
        assert ai.assess.call_count == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["error", "cancel", "missing_id", "bool_id"])
def test_failed_delivery_reuses_cached_assessment(failure):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai)
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
        session, = manager._sessions.values()
        assert session.reply_message_id is None
        assert not session.lock.locked() and not manager._message_lock.locked()
        retry = update_with("hello")
        await manager.assess_message(retry, None)
        assert session.reply_message_id == 1100
        assert len(manager._sessions) == 1

    asyncio.run(scenario())
    ai.assess.assert_called_once()


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


def test_colliding_token_is_regenerated_without_overwriting_existing_session(monkeypatch):
    manager, _ = build()

    async def scenario():
        await manager.assess_message(update_with("first"), None)
        first, = manager._sessions.values()
        tokens = iter([first.token, "A" * 16])
        monkeypatch.setattr(
            "phishreport.bot.exposure.secrets.token_urlsafe", lambda size: next(tokens),
        )
        await manager.assess_message(update_with("second", message_id=101), None)
        assert manager._sessions[first.token] is first
        assert len(manager._sessions) == 2
        second = manager._sessions["A" * 16]
        assert second.record["message"] == "second"
        assert manager._source_sessions[(ALLOWED_CHAT_ID, 42, 101)] == second.token

    asyncio.run(scenario())


def test_expired_pending_source_is_assessed_again():
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager, _ = build(ai)

    async def scenario():
        await manager.assess_message(update_with("hello"), None)
        old, = manager._sessions.values()
        old.expires_at = 0
        await manager.assess_message(update_with("hello"), None)
        assert old.token not in manager._sessions
        assert len(manager._sessions) == 1

    asyncio.run(scenario())
    assert ai.assess.call_count == 2


def test_callback_storage_does_not_block_new_assessment_and_saves_serialize():
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
        first, = manager._sessions.values()
        saving = asyncio.create_task(manager.exposure_callback(callback_for(first, "skip"), None))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            incoming = update_with("second", message_id=101)
            await asyncio.wait_for(manager.assess_message(incoming, None), 2)
            assert "Provisional assessment" in reply_text(incoming)
            second = next(s for s in manager._sessions.values() if s is not first)
            second_save = asyncio.create_task(
                manager.exposure_callback(callback_for(second, "skip"), None)
            )
            await asyncio.sleep(0)
            assert data.save.call_count == 1
        finally:
            release.set()
            await saving
        await second_save
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


def test_buffer_terminal_collects_output_and_cannot_prompt():
    terminal = BufferTerminal()

    terminal.write("Priority:", "High")
    terminal.write("done")

    assert terminal.text() == "Priority: High\ndone"
    with pytest.raises(EOFError):
        terminal.read("Name: ")


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
