"""Exposure answers: the bot record keeps link details and can reach HIGH."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import EXPOSURE_PREFIX, TelegramIOManager
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.data import DataManager
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345
SUSPICIOUS = {"suspicious": True, "credential_request": False, "insufficient_context": False}


def service(ai_manager=None):
    ai_manager = ai_manager or Mock(**{"assess.return_value": SUSPICIOUS})
    return AssessmentService(ai_manager, LogicManager())


def message_update(text=None, document=None, chat_id=ALLOWED_CHAT_ID):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="private"),
        effective_message=SimpleNamespace(
            text=text,
            document=document,
            reply_text=AsyncMock(),
        ),
    )


def callback_update(data, chat_id=ALLOWED_CHAT_ID):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="private"),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        callback_query=SimpleNamespace(
            data=data,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        ),
    )


def manager_with(assessment=None):
    data_manager = Mock(spec=DataManager)
    data_manager.replace.return_value = True
    manager = TelegramIOManager(data_manager, ALLOWED_CHAT_ID, assessment=assessment or service())
    return manager, data_manager


def test_a_pasted_link_is_kept_in_the_record():
    record = ChatRecordBuilder().build("Pay here: https://evil.example/pay now.")

    assert record["has_link"] is True
    assert record["link"] == "https://evil.example/pay"


def test_a_message_without_a_link_records_no_link():
    record = ChatRecordBuilder().build("Your parcel could not be delivered.")

    assert record["has_link"] is False
    assert record["link"] is None


def test_an_attached_document_is_recorded_as_a_file():
    document = SimpleNamespace(file_name="invoice.pdf")

    record = ChatRecordBuilder().build("see attached", document=document)

    assert record["has_file"] is True
    assert record["file_name"] == "invoice.pdf"


def test_the_assessment_reply_offers_the_exposure_buttons():
    manager, _ = manager_with()
    update = message_update("Verify your account at https://evil.example")

    asyncio.run(manager.assess_message(update, None))

    keyboard = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert labels == [
        "I clicked or downloaded something",
        "I entered a password",
        "I entered a one-time code",
        "Neither — I did not interact",
    ]
    assert keyboard.inline_keyboard[0][0].callback_data.startswith(EXPOSURE_PREFIX)


def test_clicking_a_suspicious_message_raises_it_to_high():
    manager, data_manager = manager_with()
    update = message_update("Verify your account")
    asyncio.run(manager.assess_message(update, None))
    token = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][
        0
    ].callback_data.split(":")[1]

    callback = callback_update(f"{EXPOSURE_PREFIX}{token}:interacted")
    asyncio.run(manager.exposure_answer(callback, None))

    text = callback.callback_query.edit_message_text.call_args.args[0]
    assert "Priority: High" in text
    assert "Rule-based score: 80" in text
    assert "You reported clicking a link." in text
    assert callback.callback_query.answer.assert_awaited_once() is None


def test_sharing_a_password_raises_the_score_to_the_top_band():
    manager, _ = manager_with()
    update = message_update("Verify your account")
    asyncio.run(manager.assess_message(update, None))
    token = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[1][
        0
    ].callback_data.split(":")[1]

    callback = callback_update(f"{EXPOSURE_PREFIX}{token}:password")
    asyncio.run(manager.exposure_answer(callback, None))

    text = callback.callback_query.edit_message_text.call_args.args[0]
    assert "Rule-based score: 90" in text
    assert "You reported sharing a password." in text


def test_answering_neither_keeps_the_ai_score_and_says_so():
    manager, _ = manager_with()
    update = message_update("Verify your account")
    asyncio.run(manager.assess_message(update, None))
    token = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[3][
        0
    ].callback_data.split(":")[1]

    callback = callback_update(f"{EXPOSURE_PREFIX}{token}:none")
    asyncio.run(manager.exposure_answer(callback, None))

    text = callback.callback_query.edit_message_text.call_args.args[0]
    assert "Rule-based score: 45" in text
    assert "No exposure reported" in text


def test_the_answer_updates_the_saved_report_instead_of_adding_one():
    manager, data_manager = manager_with()
    update = message_update("Verify your account")
    asyncio.run(manager.assess_message(update, None))
    token = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][
        0
    ].callback_data.split(":")[1]

    callback = callback_update(f"{EXPOSURE_PREFIX}{token}:interacted")
    asyncio.run(manager.exposure_answer(callback, None))

    data_manager.replace.assert_called_once()
    match, report = data_manager.replace.call_args.args
    assert report["result"]["priority"] == "HIGH"
    assert match({"message": "Verify your account"}) is True
    data_manager.save.assert_called_once()


def test_answering_never_calls_the_ai_a_second_time():
    ai_manager = Mock(**{"assess.return_value": SUSPICIOUS})
    manager, _ = manager_with(service(ai_manager))
    update = message_update("Verify your account")
    asyncio.run(manager.assess_message(update, None))
    token = update.effective_message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][
        0
    ].callback_data.split(":")[1]

    callback = callback_update(f"{EXPOSURE_PREFIX}{token}:interacted")
    asyncio.run(manager.exposure_answer(callback, None))

    assert ai_manager.assess.call_count == 1


def test_an_expired_question_is_reported_instead_of_scoring_nothing():
    manager, _ = manager_with()
    callback = callback_update(f"{EXPOSURE_PREFIX}deadbeef:interacted")

    asyncio.run(manager.exposure_answer(callback, None))

    assert "has expired" in callback.effective_message.reply_text.call_args.args[0]
    callback.callback_query.edit_message_text.assert_not_called()


@pytest.mark.parametrize("data", ["unrelated:1", f"{EXPOSURE_PREFIX}onlytoken"])
def test_callback_data_without_a_known_choice_is_ignored(data):
    manager, _ = manager_with()
    callback = callback_update(data)

    asyncio.run(manager.exposure_answer(callback, None))

    callback.callback_query.edit_message_text.assert_not_called()
