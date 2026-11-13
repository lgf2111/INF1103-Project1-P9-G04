"""Handle the Telegram welcome, connection check and message assessment."""

import asyncio
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.messages import (
    ChatRecordBuilder,
    ResultFormatter,
    apply_exposure,
    exposure_note,
)
from phishreport.data import DataManager

CHECK_CONNECTION = "check_connection"
EXPOSURE_PREFIX = "exposure:"
EXPOSURE_PROMPT = (
    "\n\nExposure: not confirmed. If you interacted with this message, answer below "
    "so the score reflects what happened."
)


class TelegramIOManager:
    """Telegram interface: welcome, connection check and message assessment.

    Collaborators are passed in so tests can substitute them. With no assessment
    service, text messages get a short "not available" reply instead of an assessment.
    """

    def __init__(
        self,
        data_manager: DataManager,
        allowed_chat_id: int | None = None,
        assessment=None,
        record_builder: ChatRecordBuilder | None = None,
        formatter: ResultFormatter | None = None,
        error_translator: AIErrorTranslator | None = None,
    ) -> None:
        self._data_manager = data_manager
        self._allowed_chat_id = allowed_chat_id
        self._assessment = assessment
        self._record_builder = record_builder or ChatRecordBuilder()
        self._formatter = formatter or ResultFormatter()
        self._error_translator = error_translator or AIErrorTranslator()
        # Reports are saved by read-modify-write, so overlapping saves must take turns.
        self._save_lock = asyncio.Lock()
        # One unanswered exposure question per token, holding the findings of the
        # assessment it belongs to so answering never calls the AI again.
        self._pending: dict[str, tuple[dict, dict]] = {}

    def exposure_keyboard(self, token: str) -> InlineKeyboardMarkup:
        """Offer the exposure answers that change an assessment's score."""
        choices = [
            ("I clicked or downloaded something", "interacted"),
            ("I entered a password", "password"),
            ("I entered a one-time code", "otp"),
            ("Neither — I did not interact", "none"),
        ]
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        label, callback_data=f"{EXPOSURE_PREFIX}{token}:{choice}"
                    )
                ]
                for label, choice in choices
            ]
        )

    @property
    def save_lock(self) -> asyncio.Lock:
        """Lock shared with other writers of the report history."""
        return self._save_lock

    def is_allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or chat.type != ChatType.PRIVATE:
            return False
        return self._allowed_chat_id is None or chat.id == self._allowed_chat_id

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not self.is_allowed(update) or message is None:
            return
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Check connection", callback_data=CHECK_CONNECTION)]]
        )
        await message.reply_text(
            "Welcome to PhishReport. Send me a suspicious message and I will assess it.\n\n"
            "Use /linkgmail to have me watch your Gmail and warn you about phishing emails, "
            "or /checkmail to check your unread emails now.",
            reply_markup=keyboard,
        )

    async def check_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        message = update.effective_message
        if not self.is_allowed(update) or query is None or message is None:
            return

        await query.answer()
        try:
            await asyncio.to_thread(self._data_manager.load, strict=True)
        except (OSError, ValueError):
            await message.reply_text("Could not read local history. Please try again.")
        else:
            await message.reply_text("Connection check passed.")

    async def assess_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Assess the text of a private chat message and reply with the outcome."""
        message = update.effective_message
        if not self.is_allowed(update) or message is None or not message.text:
            return
        if self._assessment is None:
            await message.reply_text("Message assessment is not available right now.")
            return

        record = self._record_builder.build(
            message.text, document=getattr(message, "document", None)
        )
        try:
            # The AI call blocks, so run it on a worker thread to keep the bot responsive.
            result, findings = await asyncio.to_thread(
                self._assessment.assess_with_findings, record
            )
        except RuntimeError as error:
            await message.reply_text(self._error_translator.translate(error))
            return
        except ValueError as error:
            await message.reply_text("Sorry, the check failed: " + str(error))
            return

        note = ""
        try:
            async with self._save_lock:
                await asyncio.to_thread(
                    self._data_manager.save, self._assessment.build_report(record, result)
                )
        except (OSError, ValueError):
            note = "\n\n(This report could not be saved locally.)"
        token = secrets.token_hex(4)
        self._pending[token] = (record, findings)
        await message.reply_text(
            self._formatter.format(result) + note + EXPOSURE_PROMPT,
            reply_markup=self.exposure_keyboard(token),
        )

    async def exposure_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Re-score an assessment with the exposure answer the user tapped."""
        query = update.callback_query
        if not self.is_allowed(update) or query is None or self._assessment is None:
            return
        data = query.data or ""
        if not data.startswith(EXPOSURE_PREFIX):
            return
        await query.answer()
        token, _, choice = data[len(EXPOSURE_PREFIX) :].partition(":")
        pending = self._pending.pop(token, None)
        message = update.effective_message
        if pending is None:
            if message is not None:
                await message.reply_text(
                    "That exposure question has expired. Send the message again to re-check it."
                )
            return

        record, findings = pending
        updated = apply_exposure(record, choice)
        result = await asyncio.to_thread(self._assessment.reassess, updated, findings)
        note = ""
        try:
            async with self._save_lock:
                report = self._assessment.build_report(updated, result)
                message_text = report["message"]
                replaced = await asyncio.to_thread(
                    self._data_manager.replace,
                    lambda stored: stored.get("message") == message_text,
                    report,
                )
                if not replaced:
                    await asyncio.to_thread(self._data_manager.save, report)
        except (OSError, ValueError):
            note = "\n\n(This report could not be saved locally.)"

        text = self._formatter.format(result) + exposure_note(choice) + note
        try:
            await query.edit_message_text(text)
        except BadRequest:
            # The text can be unchanged (answering "neither" twice); the reply stands.
            pass
