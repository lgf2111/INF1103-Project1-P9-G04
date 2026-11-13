"""Handle the Telegram welcome, connection check and message assessment."""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.feedback_ui import (
    CATEGORY_CODES,
    CATEGORY_LABELS,
    assessment_feedback_keyboard,
    corrected_priority_keyboard,
    feedback_category_keyboard,
    feedback_comment_keyboard,
)
from phishreport.bot.messages import ChatRecordBuilder, ResultFormatter
from phishreport.data import DataManager

CHECK_CONNECTION = "check_connection"


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
        feedback_service=None,
    ) -> None:
        self._data_manager = data_manager
        self._allowed_chat_id = allowed_chat_id
        self._assessment = assessment
        self._record_builder = record_builder or ChatRecordBuilder()
        self._formatter = formatter or ResultFormatter()
        self._error_translator = error_translator or AIErrorTranslator()
        self._feedback_service = feedback_service
        # Reports are saved by read-modify-write, so overlapping saves must take turns.
        self._save_lock = asyncio.Lock()
        self._feedback_lock = asyncio.Lock()

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
        pending = self._pending_feedback(context)
        if pending is not None:
            await self._submit_feedback(update, context, pending, message.text)
            return
        if self._assessment is None:
            await message.reply_text("Message assessment is not available right now.")
            return

        record = self._record_builder.build(message.text)
        try:
            # The AI call blocks, so run it on a worker thread to keep the bot responsive.
            result = await asyncio.to_thread(self._assessment.assess, record)
        except RuntimeError as error:
            await message.reply_text(self._error_translator.translate(error))
            return
        except ValueError as error:
            await message.reply_text("Sorry, the check failed: " + str(error))
            return

        note = ""
        saved = False
        try:
            async with self._save_lock:
                await asyncio.to_thread(
                    self._data_manager.save, self._assessment.build_report(record, result)
                )
            saved = True
        except (OSError, ValueError):
            note = "\n\n(This report could not be saved locally.)"
        reply_markup = (
            assessment_feedback_keyboard(result["assessment_id"])
            if saved and self._feedback_service is not None
            else None
        )
        if reply_markup is None:
            await message.reply_text(self._formatter.format(result) + note)
        else:
            await message.reply_text(
                self._formatter.format(result) + note, reply_markup=reply_markup
            )

    async def handle_feedback_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle assessment feedback buttons and preserve one user's correction state."""
        query = update.callback_query
        message = update.effective_message
        if (
            not self.is_allowed(update)
            or query is None
            or message is None
            or self._feedback_service is None
        ):
            return
        await query.answer()
        parts = query.data.split(":") if isinstance(query.data, str) else []
        if len(parts) < 3 or parts[0] != "fb":
            return

        action = parts[1]
        assessment_id = parts[-1]
        if action == "o" and len(parts) == 3:
            try:
                await asyncio.to_thread(self._load_assessment_result, assessment_id)
            except (OSError, ValueError):
                await message.reply_text("This assessment is no longer available for feedback.")
                return
            await message.reply_text(
                "What would you like to correct?",
                reply_markup=feedback_category_keyboard(assessment_id),
            )
            return

        user_data = self._user_data(context)
        if user_data is None:
            await message.reply_text("This feedback session expired. Please start again.")
            return
        if action == "x" and len(parts) == 3:
            pending = user_data.get("pending_feedback")
            if pending is not None and pending.get("assessment_id") == assessment_id:
                user_data.pop("pending_feedback", None)
            await message.reply_text("Feedback cancelled.")
            return

        if action == "c" and len(parts) == 4:
            code = parts[2]
            category = CATEGORY_CODES.get(code)
            if category is None:
                return
            try:
                await asyncio.to_thread(self._load_assessment_result, assessment_id)
            except (OSError, ValueError):
                await message.reply_text("This assessment is no longer available for feedback.")
                return
            user_data["pending_feedback"] = {
                "assessment_id": assessment_id,
                "category": category,
                "corrected_priority": None,
            }
            if category == "incorrect_priority":
                await message.reply_text(
                    "What should the priority be?",
                    reply_markup=corrected_priority_keyboard(assessment_id),
                )
            else:
                await message.reply_text(
                    f"You selected {CATEGORY_LABELS[code]}. Reply with details (up to 2000 "
                    "characters), or submit without a comment.",
                    reply_markup=feedback_comment_keyboard(assessment_id),
                )
            return

        if action == "p" and len(parts) == 4:
            pending = user_data.get("pending_feedback")
            priorities = {"H": "HIGH", "M": "MEDIUM", "L": "LOW"}
            corrected_priority = priorities.get(parts[2])
            if (
                pending is None
                or pending.get("assessment_id") != assessment_id
                or pending.get("category") != "incorrect_priority"
                or corrected_priority is None
            ):
                await message.reply_text("This feedback session expired. Please start again.")
                return
            pending["corrected_priority"] = corrected_priority
            await message.reply_text(
                f"You selected {corrected_priority}. Reply with details (up to 2000 "
                "characters), or submit without a comment.",
                reply_markup=feedback_comment_keyboard(assessment_id),
            )
            return

        if action == "s" and len(parts) == 3:
            pending = user_data.get("pending_feedback")
            if pending is None or pending.get("assessment_id") != assessment_id:
                await message.reply_text("This feedback session expired. Please start again.")
                return
            await self._submit_feedback(update, context, pending, None)

    async def _submit_feedback(self, update, context, pending: dict, comment: str | None) -> None:
        """Save one pending correction against the original persisted assessment."""
        message = update.effective_message
        if len(comment or "") > 2000:
            await message.reply_text("Feedback details must be at most 2000 characters.")
            return
        user_data = self._user_data(context)
        if user_data is None:
            await message.reply_text("This feedback session expired. Please start again.")
            return
        assessment_id = pending["assessment_id"]
        async with self._feedback_lock:
            current = user_data.get("pending_feedback")
            if current is not pending or current.get("assessment_id") != assessment_id:
                await message.reply_text("This feedback session expired. Please start again.")
                return
            try:
                result = await asyncio.to_thread(self._load_assessment_result, assessment_id)
                await asyncio.to_thread(
                    self._feedback_service.submit,
                    assessment_id=assessment_id,
                    assessment_result=result,
                    category=pending["category"],
                    corrected_priority=pending.get("corrected_priority"),
                    comment=comment or None,
                )
            except (OSError, ValueError):
                await message.reply_text("Could not save your feedback. Please try again.")
                return
            user_data.pop("pending_feedback", None)
        await message.reply_text("Thank you. Your feedback was saved for review.")

    def _load_assessment_result(self, assessment_id: str) -> dict:
        """Load one v3 report by ID and return its result with the ID attached."""
        for report in self._data_manager.load(strict=True):
            if report.get("assessment_id") == assessment_id and report.get("schema_version") == 3:
                return {**report["result"], "assessment_id": assessment_id}
        raise ValueError("Assessment was not found.")

    @staticmethod
    def _user_data(context):
        """Return per-user update state when the Telegram context provides it."""
        user_data = getattr(context, "user_data", None)
        return user_data if isinstance(user_data, dict) else None

    def _pending_feedback(self, context):
        """Return the active feedback correction, if the user has one."""
        user_data = self._user_data(context)
        return None if user_data is None else user_data.get("pending_feedback")
