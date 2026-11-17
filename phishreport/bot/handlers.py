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
from phishreport.assessment import AssessmentSnapshot
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.feedback_ui import (
    CATEGORY_CODES,
    CATEGORY_LABELS,
    corrected_priority_keyboard,
    feedback_category_keyboard,
    feedback_comment_keyboard,
)
from phishreport.bot.messages import (
    EXPOSURE_CALLBACK_PREFIX,
    ChatRecordBuilder,
    ResultFormatter,
    build_exposure_keyboard,
)
from phishreport.data import DataManager
from phishreport.errors import AssessmentError
from phishreport.io.check_command import CheckOutcome
from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.commands import CommandRequest, CommandRouter
from phishreport.model import SCHEMA_VERSION, Report

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

        Invalid requests do not trigger housekeeping. Reports are saved before
        their card is shown, so an expired or evicted session only costs the
        optional follow-up tap, never stored history.
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
            if now >= session.expires_at and not session.lock.locked():
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

    async def _write_report(self, report: dict, commit=None) -> None:
        """Append one validated revision, shielding the write from cancellation.

        Callers must not already hold self._save_lock. `commit` runs only after
        the revision reached storage, including when cancellation arrives late,
        so a retry never saves the same revision twice.
        """
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
            if commit is not None:
                commit()
            if cancellation is not None:
                raise cancellation

    async def exposure_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Apply one follow-up answer, save its revision and edit the saved card."""
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
            "This assessment is closed. "
            "Paste the message again to start a new assessment."
        )
        payload = getattr(query, "data", None)
        match = re.fullmatch(
            rf"{re.escape(EXPOSURE_CALLBACK_PREFIX)}:([A-Za-z0-9_-]{{16}}):"
            r"(clicked|password|nothing)",
            payload,
        ) if isinstance(payload, str) else None
        session = self._find_exposure_session(update, match[1]) if match else None
        try:
            if session is None:
                await query.edit_message_text(unavailable, reply_markup=None)
                return

            failed = False
            # Hold the lock across the save and the edit: another tap cannot
            # replace a newer rendered state with an older reply.
            async with session.lock:
                if time.monotonic() >= session.expires_at:
                    await query.edit_message_text(unavailable, reply_markup=None)
                    return
                if match[2] == "nothing":
                    session.dismiss()
                else:
                    try:
                        if self._assessment is None:
                            raise ValueError("Message assessment is not available")
                        candidate = session.answer(match[2], self._assessment)
                        if candidate is not None:
                            exposure, result = candidate
                            report = session.build_report(
                                self._assessment, exposure=exposure, result=result,
                            )
                            await self._write_report(
                                report,
                                lambda: session.commit(exposure, result, report),
                            )
                    except (AssessmentError, OSError, ValueError, RuntimeError):
                        failed = True

                text = self._formatter.format(session.result, session=session)
                if failed:
                    text = "Could not update the assessment. Please try again.\n\n" + text
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
        except (OSError, ValueError, AssessmentError):
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

        pending = self._pending_feedback(context)
        if pending is not None:
            await self._submit_feedback(update, context, pending, text)
            return

        command = None
        failure_messages = {
            "history": "Could not read local history. Please try again.",
            "command": "Sorry, the command failed. Please try again.",
        }
        if text.lstrip().startswith("/"):
            catalog = discover_commands(CommandCapabilities(
                prepare_record=lambda request: self._record_builder.build(request.text),
                assess_record=lambda record: self._assessment.assess_with_findings(record),
                session_status=lambda request: status_label,
                report_count=lambda: len(self._data_manager.load(strict=True)),
            ))
            router = CommandRouter(catalog)
            command = router.resolve(text)
            if command is not None:
                # Snapshot owned live sessions on-loop before the history read.
                now = time.monotonic()
                count = sum(
                    session.chat_id == chat_id and session.user_id == user_id
                    and not session.dismissed and session.expires_at > now
                    for session in self._sessions.values()
                )
                status_label = f"Active exposure sessions awaiting answers: {count}"
            if command is not None and command.policy.execution == "reply":
                try:
                    reply = await asyncio.to_thread(
                        router.route, CommandRequest(text, "telegram"),
                    )
                except (AssessmentError, OSError, ValueError, RuntimeError) as error:
                    if command.policy.failure != "assessment":
                        failure_text = failure_messages[command.policy.failure]
                    elif isinstance(error, AssessmentError):
                        failure_text = self._error_translator.translate(error)
                    elif isinstance(error, (ValueError, RuntimeError)):
                        raise
                    else:
                        failure_text = "Sorry, the check failed. Please try again."
                    await message.reply_text(failure_text)
                else:
                    await message.reply_text(reply.text)
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
                        "Too many recent assessments. Please try again shortly."
                    )
                    return
                if command is None:
                    try:
                        record = self._record_builder.build(text)
                    except AssessmentError as error:
                        await message.reply_text(self._error_translator.translate(error))
                        return
                    except (ValueError, OSError):
                        await message.reply_text("Invalid input. Please revise it and try again.")
                        return
                if command is not None:
                    request = CommandRequest(text, "telegram")
                    try:
                        reply = await asyncio.to_thread(router.route, request)
                    except (AssessmentError, OSError, ValueError, RuntimeError) as error:
                        if command.policy.failure != "assessment":
                            failure_text = failure_messages[command.policy.failure]
                        elif isinstance(error, AssessmentError):
                            failure_text = self._error_translator.translate(error)
                        elif isinstance(error, (ValueError, RuntimeError)):
                            raise
                        else:
                            failure_text = "Sorry, the check failed. Please try again."
                        await message.reply_text(failure_text)
                        return
                    if reply.kind != "assessment":
                        await message.reply_text(reply.text)
                        return
                    outcome = request.session["check_outcome"]
                    if (not isinstance(outcome, CheckOutcome)
                            or not isinstance(outcome.findings, dict)):
                        raise TypeError(
                            "Assessment commands must retain a CheckOutcome with findings."
                        )
                    record = outcome.record
                    snapshot = AssessmentSnapshot(outcome.findings, outcome.result)
                else:
                    try:
                        # Retain findings for later answers; AI work stays off-loop.
                        snapshot = await asyncio.to_thread(
                            self._assessment.assess_with_findings, record,
                        )
                    except AssessmentError as error:
                        await message.reply_text(self._error_translator.translate(error))
                        return

                session = ExposureSession(
                    record, snapshot, chat_id=chat_id, user_id=user_id, message_id=message_id,
                )
                while session.token in self._sessions:
                    session.token = secrets.token_urlsafe(12)
                # Index before delivery: Telegram failures must not lose the AI
                # snapshot or the saved revision when delivery is retried.
                self._sessions[session.token] = session
                self._source_sessions[(chat_id, user_id, message_id)] = session.token

            if session.reply_message_id is not None:
                return
            async with session.lock:
                if session.reply_message_id is not None:
                    return
                if not session.saved:
                    if self._assessment is None:
                        await message.reply_text("Message assessment is not available right now.")
                        return
                    try:
                        report = session.build_report(self._assessment)
                        await self._write_report(report, lambda: session.commit(
                            session.exposure, session.result, report,
                        ))
                    except asyncio.CancelledError:
                        raise
                    except (AssessmentError, OSError, ValueError, RuntimeError):
                        self._sessions.pop(session.token, None)
                        self._source_sessions.pop((chat_id, user_id, message_id), None)
                        await message.reply_text(
                            "Could not save the report. Please try again."
                        )
                        return
                reply = await message.reply_text(
                    self._formatter.format(session.result, session=session),
                    reply_markup=build_exposure_keyboard(session),
                )
                reply_id = getattr(reply, "message_id", None)
                if type(reply_id) is int:
                    session.reply_message_id = reply_id

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
            except AssessmentError:
                await message.reply_text(
                    "Could not load the assessment for feedback. Please try again."
                )
                return
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
            except AssessmentError:
                await message.reply_text(
                    "Could not load the assessment for feedback. Please try again."
                )
                return
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
            except (AssessmentError, OSError, ValueError):
                await message.reply_text("Could not save your feedback. Please try again.")
                return
            user_data.pop("pending_feedback", None)
        await message.reply_text("Thank you. Your feedback was saved for review.")

    def _load_assessment_result(self, assessment_id: str) -> dict:
        """Load one v3 report by ID and return its newest revision with the ID attached."""
        for source in reversed(self._data_manager.load(strict=True)):
            report = Report(source)
            if report.assessment_id == assessment_id and report.schema_version == SCHEMA_VERSION:
                return {**report.to_dict()["result"], "assessment_id": assessment_id}
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
