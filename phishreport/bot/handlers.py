"""Handle the Telegram welcome, connection check and message assessment."""

import asyncio
import re
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.messages import (
    EXPOSURE_CALLBACK_PREFIX,
    ChatRecordBuilder,
    ResultFormatter,
    build_exposure_keyboard,
)
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

    async def _save_exposure_report(self, session: ExposureSession) -> None:
        """Complete and save once, retaining both locks until storage finishes.

        Callers must not already hold session.lock. A failed write leaves the
        completed snapshot available for retry. Cancellation after writing starts
        waits for its outcome; success is recorded before cancellation propagates.
        """
        async with session.lock:
            if session.saved:
                return
            if self._assessment is None:
                raise ValueError("Message assessment is not available")
            report = session.complete(self._assessment)
            async with self._save_lock:
                write_task = asyncio.create_task(asyncio.to_thread(self._data_manager.save, report))
                cancellation = None
                while True:
                    try:
                        await asyncio.shield(write_task)
                        break
                    except asyncio.CancelledError as error:
                        # A cancelled worker task cannot deliver an outcome. This
                        # guard also prevents spinning during process shutdown.
                        if write_task.cancelled():
                            raise
                        if cancellation is None:
                            cancellation = error
                session.saved = True
                if cancellation is not None:
                    raise cancellation

    async def exposure_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Acknowledge exposure buttons, serialize answers and render current state."""
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        await query.answer()
        chat = getattr(update, "effective_chat", None)
        if (getattr(chat, "type", None) != ChatType.PRIVATE
                or type(getattr(chat, "id", None)) is not int
                or not self.is_allowed(update)):
            return

        unavailable = (
            "These questions are not available. "
            "Paste the message again to start a new assessment."
        )
        payload = getattr(query, "data", None)
        match = re.fullmatch(
            rf"{re.escape(EXPOSURE_CALLBACK_PREFIX)}:([A-Za-z0-9_-]{{16}}):"
            r"(clicked|downloaded|both|neither|password|otp|no_disclosure|finish|skip|retry)",
            payload,
        ) if isinstance(payload, str) else None
        session = self._find_exposure_session(update, match[1]) if match else None
        try:
            if session is None:
                await query.edit_message_text(unavailable, reply_markup=None)
                return

            action = match[2]
            feedback = ""
            try:
                if action in {"finish", "skip"}:
                    # The helper owns session.lock, including during storage.
                    await self._save_exposure_report(session)
                elif action == "retry":
                    async with session.lock:
                        if not session.completed:
                            raise ValueError("No completed report to retry")
                    await self._save_exposure_report(session)
                else:
                    async with session.lock:
                        # Replayed answer buttons only render the frozen report.
                        if not session.completed:
                            if self._assessment is None:
                                raise ValueError("Message assessment is not available")
                            session.apply_answer(action, self._assessment)
            except (OSError, ValueError, RuntimeError):
                feedback = "Could not update the assessment. Please try again.\n\n"

            # Hold the lock across the edit: another button cannot replace a
            # newer rendered state with an older reply after a slow Telegram call.
            async with session.lock:
                if not session.completed and time.monotonic() >= session.expires_at:
                    await query.edit_message_text(unavailable, reply_markup=None)
                else:
                    text = self._formatter.format(session.result, session=session)
                    if feedback and not session.completed:
                        text = feedback + text
                    await query.edit_message_text(
                        text, reply_markup=build_exposure_keyboard(session),
                    )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                raise

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
        """Cache one assessment per source and deliver provisional exposure questions."""
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        message = getattr(update, "effective_message", None)
        chat_id = getattr(chat, "id", None)
        user_id = getattr(user, "id", None)
        message_id = getattr(message, "message_id", None)
        text = getattr(message, "text", None)
        if (any(type(value) is not int for value in (chat_id, user_id, message_id))
                or getattr(chat, "type", None) != ChatType.PRIVATE
                or getattr(update, "callback_query", None) is not None
                or not isinstance(text, str) or not text.strip()
                or not self.is_allowed(update)):
            return

        # Initialize before the first await, so concurrent ingress shares one
        # lock. This lock never waits for callback storage or future answers.
        if not hasattr(self, "_message_lock"):
            self._message_lock = asyncio.Lock()
        async with self._message_lock:
            if self._assessment is None:
                await message.reply_text("Message assessment is not available right now.")
                return

            session = self._find_exposure_session(update)
            if session is None:
                if len(self._sessions) >= self._session_limit:
                    await message.reply_text(
                        "Too many pending assessments. "
                        "Finish or skip an earlier one, then try again."
                    )
                    return
                record = self._record_builder.build(text)
                try:
                    # Retain findings for later answers; AI work stays off-loop.
                    snapshot = await asyncio.to_thread(
                        self._assessment.assess_with_findings, record,
                    )
                except RuntimeError as error:
                    await message.reply_text(self._error_translator.translate(error))
                    return
                except ValueError as error:
                    await message.reply_text("Sorry, the check failed: " + str(error))
                    return

                session = ExposureSession(
                    record, snapshot, chat_id=chat_id, user_id=user_id, message_id=message_id,
                )
                while session.token in self._sessions:
                    session.token = secrets.token_urlsafe(12)
                # Index before delivery: Telegram failures must not lose the AI
                # snapshot or any completed report when delivery is retried.
                self._sessions[session.token] = session
                self._source_sessions[(chat_id, user_id, message_id)] = session.token

            if session.reply_message_id is not None:
                return
            async with session.lock:
                if session.reply_message_id is not None:
                    return
                reply = await message.reply_text(
                    self._formatter.format(session.result, session=session),
                    reply_markup=build_exposure_keyboard(session),
                )
                reply_id = getattr(reply, "message_id", None)
                if type(reply_id) is int:
                    session.reply_message_id = reply_id
