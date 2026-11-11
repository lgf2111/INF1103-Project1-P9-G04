"""Assess chat messages through the Telegram handler with fake updates and no live AI."""

import asyncio
import threading
import time
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
from phishreport.data import DataManager
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def update_with(text, chat_id=ALLOWED_CHAT_ID, chat_type="private"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_message=SimpleNamespace(text=text, reply_text=AsyncMock()),
    )


def build(ai_manager=None, data_manager=None, allowed_chat_id=ALLOWED_CHAT_ID):
    ai_manager = ai_manager or Mock(**{"assess.return_value": FINDINGS})
    data_manager = data_manager or Mock(spec=DataManager)
    service = AssessmentService(ai_manager, LogicManager())
    return TelegramIOManager(data_manager, allowed_chat_id, assessment=service), data_manager


def reply_text(update):
    return update.effective_message.reply_text.call_args.args[0]


def test_a_text_message_is_assessed_saved_and_answered():
    manager, data_manager = build()
    update = update_with("Verify your password now")

    asyncio.run(manager.assess_message(update, None))

    reply = reply_text(update)
    assert "Priority: Medium" in reply
    assert "Rule-based score: 60" in reply
    assert reply.endswith(ResultFormatter.FOOTER)
    (report,), _ = data_manager.save.call_args
    assert report["schema_version"] == 2
    assert report["channel"] == "chat"
    assert report["message"] == "Verify your password now"
    assert report["result"]["score"] == 60


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


def test_a_save_failure_still_delivers_the_assessment():
    data_manager = Mock(spec=DataManager)
    data_manager.save.side_effect = OSError("disk full")
    manager, _ = build(data_manager=data_manager)
    update = update_with("hello")

    asyncio.run(manager.assess_message(update, None))

    reply = reply_text(update)
    assert "Priority: Medium" in reply
    assert "could not be saved locally" in reply


def test_the_blocking_ai_call_runs_off_the_event_loop_thread():
    seen = {}

    def assess(record):
        seen["thread"] = threading.current_thread()
        return FINDINGS

    manager, _ = build(Mock(assess=assess))

    asyncio.run(manager.assess_message(update_with("hello"), None))

    assert seen["thread"] is not threading.main_thread()


def test_overlapping_saves_take_turns():
    active = {"now": 0, "peak": 0}

    def save(report):
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.05)
        active["now"] -= 1

    data_manager = Mock(spec=DataManager)
    data_manager.save.side_effect = save
    manager, _ = build(data_manager=data_manager)

    async def two_messages():
        await asyncio.gather(
            manager.assess_message(update_with("one"), None),
            manager.assess_message(update_with("two"), None),
        )

    asyncio.run(two_messages())

    assert data_manager.save.call_count == 2
    assert active["peak"] == 1


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
