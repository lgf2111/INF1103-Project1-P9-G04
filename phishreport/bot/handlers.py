"""Handle the Telegram welcome, connection check and message assessment."""

import asyncio
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.exposure import ExposureSession
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
    ) -> None:
        self._data_manager = data_manager
        self._allowed_chat_id = allowed_chat_id
        self._assessment = assessment
        self._record_builder = record_builder or ChatRecordBuilder()
        self._formatter = formatter or ResultFormatter()
        self._error_translator = error_translator or AIErrorTranslator()
        # Reports are saved by read-modify-write, so overlapping saves must take turns.
        self._save_lock = asyncio.Lock()
        # Keep exposure sessions by token and source (chat, user, message) identity.
        self._sessions: dict[str, ExposureSession] = {}
        self._source_sessions: dict[tuple[int, int, int], str] = {}
        self._session_limit = 1000

    @property
    def save_lock(self) -> asyncio.Lock:
        """Lock shared with other writers of the report history."""
        return self._save_lock

    def is_allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        if chat is None or chat.type != ChatType.PRIVATE:
            return False
        return self._allowed_chat_id is None or chat.id == self._allowed_chat_id

    def _find_exposure_session(
        self, update: Update, token: str | None = None,
    ) -> ExposureSession | None:
        """Resolve an owned session and lazily maintain the in-memory caches.

        Invalid requests do not trigger housekeeping. Keep locked work and
        completed unsaved reports available for finalization/storage retries.
        Only a new source request may make room by evicting saved sessions.
        """
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        message = getattr(update, "effective_message", None)
        chat_id = getattr(chat, "id", None)
        user_id = getattr(user, "id", None)
        message_id = getattr(message, "message_id", None)
        if any(type(value) is not int for value in (chat_id, user_id, message_id)):
            return None
        if getattr(chat, "type", None) != ChatType.PRIVATE or not self.is_allowed(update):
            return None

        query = getattr(update, "callback_query", None)
        if token is None:
            if query is not None:
                return None
            source = (chat_id, user_id, message_id)
            candidate = self._sessions.get(self._source_sessions.get(source))
            if candidate is not None and (
                candidate.chat_id, candidate.user_id, candidate.message_id
            ) != source:
                return None
        else:
            if query is None or not isinstance(token, str):
                return None
            if re.fullmatch(r"[A-Za-z0-9_-]{16}", token) is None:
                return None
            candidate = self._sessions.get(token)
            if candidate is None or (
                candidate.chat_id != chat_id or candidate.user_id != user_id
                or candidate.reply_message_id is None
                or candidate.reply_message_id != message_id
            ):
                return None

        now = time.monotonic()
        for cached_token, session in list(self._sessions.items()):
            if (now >= session.expires_at and not session.lock.locked()
                    and (not session.completed or session.saved)):
                del self._sessions[cached_token]

        if token is None and candidate is None and len(self._sessions) >= self._session_limit:
            saved = sorted(
                ((cached_token, session) for cached_token, session in self._sessions.items()
                 if session.saved and not session.lock.locked()),
                key=lambda item: item[1].created_at,
            )
            for cached_token, _session in saved:
                if len(self._sessions) < self._session_limit:
                    break
                del self._sessions[cached_token]

        for source, cached_token in list(self._source_sessions.items()):
            if cached_token not in self._sessions:
                del self._source_sessions[source]
        if candidate is not None and candidate.token in self._sessions:
            return candidate
        return None

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
        try:
            async with self._save_lock:
                await asyncio.to_thread(
                    self._data_manager.save, self._assessment.build_report(record, result)
                )
        except (OSError, ValueError):
            note = "\n\n(This report could not be saved locally.)"
        await message.reply_text(self._formatter.format(result) + note)
