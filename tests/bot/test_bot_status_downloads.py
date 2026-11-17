"""Status downloads: CSV and summary documents built from saved reports."""

import asyncio
import csv
import io
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import STATUS_CSV_CALLBACK, STATUS_SUMMARY_CALLBACK
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io.report_csv import CSV_COLUMNS

CHAT_ID = 123


def saved_report(number: int) -> dict:
    """Return one minimal version-3 report with a result and message."""
    return {
        "schema_version": 3,
        "assessment_id": f"saved-{number}",
        "channel": "email",
        "message": f"Message {number}",
        "result": {"score": 60, "priority": "MEDIUM", "reasons": [], "checklist": []},
    }


def build_manager(tmp_path, records, allowed_chat_id=CHAT_ID):
    """Write history through the real storage layer and build the bot manager."""
    storage = JsonReportStorage(tmp_path / "reports.json")
    storage.write_records(records)
    return TelegramIOManager(DataManager(storage), allowed_chat_id)


def status_update(text="/status"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=CHAT_ID, type="private"),
        effective_user=SimpleNamespace(id=42), callback_query=None,
        effective_message=SimpleNamespace(
            text=text, message_id=100, reply_text=AsyncMock(),
        ),
    )


def callback_update(data, *, chat_id=CHAT_ID):
    query = SimpleNamespace(data=data, answer=AsyncMock())
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="private"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(message_id=100, reply_text=AsyncMock()),
        callback_query=query,
    )


def callback_context():
    bot = SimpleNamespace(send_document=AsyncMock())
    return SimpleNamespace(bot=bot), bot


def test_status_with_saved_reports_offers_both_downloads(tmp_path):
    """One saved report adds the stable CSV and summary callback row."""
    manager = build_manager(tmp_path, [saved_report(1)])
    update = status_update()

    asyncio.run(manager.assess_message(update, None))

    reply = update.effective_message.reply_text.await_args
    assert reply.args[0] == (
        "Session: Active exposure sessions awaiting answers: 0\nSaved reports: 1"
    )
    [[csv_button, summary_button]] = reply.kwargs["reply_markup"].inline_keyboard
    assert csv_button.callback_data == STATUS_CSV_CALLBACK == "status:csv"
    assert summary_button.callback_data == STATUS_SUMMARY_CALLBACK == "status:summary"
    assert csv_button.text == "Download all reports (CSV)"
    assert summary_button.text == "Download summary (TXT)"


def test_csv_callback_sends_the_cli_header_and_a_dated_filename(tmp_path):
    """The CSV document is the same column contract as the CLI export."""
    manager = build_manager(tmp_path, [saved_report(1), saved_report(2)])
    update = callback_update(STATUS_CSV_CALLBACK)
    context, bot = callback_context()

    asyncio.run(manager.status_callback(update, context))

    update.callback_query.answer.assert_awaited_once_with()
    bot.send_document.assert_awaited_once()
    sent = bot.send_document.await_args.kwargs
    assert sent["chat_id"] == CHAT_ID
    assert re.fullmatch(r"phishreport-\d{4}-\d{2}-\d{2}\.csv", sent["filename"])
    rows = list(csv.reader(io.StringIO(sent["document"].decode("utf-8"))))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert [row[4] for row in rows[1:]] == ["Message 1", "Message 2"]


def test_summary_callback_sends_a_text_file_with_the_report_count(tmp_path):
    """The summary document carries the counts the CLI prints."""
    manager = build_manager(tmp_path, [saved_report(1), saved_report(2)])
    update = callback_update(STATUS_SUMMARY_CALLBACK)
    context, bot = callback_context()

    asyncio.run(manager.status_callback(update, context))

    sent = bot.send_document.await_args.kwargs
    assert re.fullmatch(
        r"phishreport-summary-\d{4}-\d{2}-\d{2}\.txt", sent["filename"],
    )
    text = sent["document"].decode("utf-8")
    assert "Reports: 2" in text
    assert "Reports by priority:" in text
    assert "Reports by channel:" in text
    assert "Average: 60.0" in text
    assert "Clicked a link: 0" in text
    assert "Submitted a password or code: 0" in text


def test_status_with_an_empty_store_shows_no_buttons(tmp_path):
    """Nothing saved yet ends the status text and offers no download."""
    manager = build_manager(tmp_path, [])
    update = status_update()

    asyncio.run(manager.assess_message(update, None))

    update.effective_message.reply_text.assert_awaited_once_with(
        "Session: Active exposure sessions awaiting answers: 0\n"
        "Saved reports: 0\n\nNothing saved yet."
    )


def test_publisher_failure_sends_one_sentence_without_escaping(tmp_path):
    """A failed send_document becomes one short reply, not a traceback."""
    manager = build_manager(tmp_path, [saved_report(1)])
    update = callback_update(STATUS_CSV_CALLBACK)
    context, bot = callback_context()
    bot.send_document.side_effect = RuntimeError("PRIVATE_FAILURE")

    asyncio.run(manager.status_callback(update, context))

    update.effective_message.reply_text.assert_awaited_once_with(
        "Could not prepare the download. Please try again."
    )


def test_a_disallowed_chat_gets_no_document(tmp_path):
    """The allowed-chat guard applies to downloads as well as assessments."""
    manager = build_manager(tmp_path, [saved_report(1)])
    update = callback_update(STATUS_CSV_CALLBACK, chat_id=999)
    context, bot = callback_context()

    asyncio.run(manager.status_callback(update, context))

    update.callback_query.answer.assert_awaited_once_with()
    bot.send_document.assert_not_awaited()
    update.effective_message.reply_text.assert_not_awaited()
