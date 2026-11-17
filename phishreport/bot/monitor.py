"""Poll linked Gmail inboxes in the background and alert on phishing."""

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from telegram import Bot
from telegram.constants import ParseMode

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.feedback_ui import FeedbackKeyboardFactory
from phishreport.bot.gmail import (
    AccountStore,
    EmailSource,
    GmailMailbox,
    LinkedAccount,
    MailboxError,
)
from phishreport.bot.messages import ChatRecordBuilder, PhishingAlertFormatter
from phishreport.errors import AssessmentError, InvalidInput
from phishreport.io.eml import EmlReader
from phishreport.logging_setup import AppLogging

logger = AppLogging.get_logger("email_monitor")

ALERT_PRIORITIES = {"MEDIUM", "HIGH"}
POLL_SECONDS = 60
MANUAL_LIMIT = 20  # Newest unread emails checked by /checkmail.


class Outcome(Enum):
    """What happens to one email's place in the inbox cursor.

    SENT:  fully processed (assessed, saved, and alerted if it needed one). Advance.
    DROP:  deliberately and permanently unprocessable; retrying can never succeed.
           Only two cases: bytes that cannot be parsed into an email, and content the
           AI rejects as invalid input. Advance, so one bad email cannot block the inbox.
    RETRY: anything else that failed (AI outage, storage, Telegram, unexpected error,
           link check). The cursor stays put and the next cycle retries this email.
    LINK_CHANGED: the link was revoked or replaced mid-flight. Deliver nothing, alert
           nothing, and do not advance the cursor; the new link owns the inbox now.
    """

    SENT = "sent"
    RETRY = "retry"
    DROP = "drop"
    LINK_CHANGED = "link_changed"


class Handled(NamedTuple):
    outcome: Outcome
    flagged: bool = False


@dataclass
class _Pending:
    """Work already done for an email whose delivery or save has not finished."""

    record: dict
    result: dict
    sender: str
    report: dict
    saved: bool = False


class EmailMonitor:
    """Check each linked inbox every cycle and message the owner about phishing."""

    def __init__(
        self,
        bot: Bot,
        store: AccountStore,
        assessment,
        data_manager,
        save_lock: asyncio.Lock,
        interval: float = POLL_SECONDS,
        mailbox_factory: Callable[[str, str], GmailMailbox] = GmailMailbox,
        reader: EmlReader | None = None,
        formatter: PhishingAlertFormatter | None = None,
        feedback_service=None,
    ) -> None:
        self._bot = bot
        self._store = store
        self._assessment = assessment
        self._data_manager = data_manager
        self._save_lock = save_lock
        self._interval = interval
        self._mailbox_factory = mailbox_factory
        self._reader = reader or EmlReader()
        self._formatter = formatter or PhishingAlertFormatter()
        self._feedback_service = feedback_service
        self._builder = ChatRecordBuilder()
        self._errors = AIErrorTranslator()
        # Keeps the assessment of a failed save/send so a retry neither re-asks the AI
        # nor saves a duplicate report. Lost on restart, which only costs one re-check.
        self._pending: dict[tuple, _Pending] = {}

    @staticmethod
    def _say(text: str) -> None:
        """Show progress in the terminal. Never include email content or secrets."""
        print(f"[email] {text}", flush=True)

    async def run(self) -> None:
        """Poll forever; one failing cycle never stops the loop."""
        while True:
            try:
                await self.poll_once()
            except Exception as error:
                AppLogging.log_failure(logger, "Email polling cycle failed")
                self._say(f"Checking the inbox failed ({type(error).__name__}); will retry.")
            await asyncio.sleep(self._interval)

    async def poll_once(self) -> None:
        for account in await asyncio.to_thread(self._store.all):
            await self._poll_account(account)

    async def _poll_account(self, account: LinkedAccount) -> None:
        mailbox = self._mailbox_factory(account.address, account.password)
        try:
            emails = await asyncio.to_thread(mailbox.new_since, account.last_uid)
        except MailboxError as error:
            AppLogging.log_failure(logger, "Could not read a linked inbox")
            self._say("Could not reach Gmail. Will retry." if error.retryable
                      else "Gmail rejected the saved login.")
            if not error.retryable:
                try:
                    removed = await asyncio.to_thread(
                        self._store.remove, account.chat_id, expected=account,
                    )
                except (AssessmentError, OSError, ValueError):
                    self._say("Could not remove the Gmail link. Will retry.")
                    return
                if not removed:
                    return
                await self._send(
                    account.chat_id,
                    "Gmail rejected the saved login, so I unlinked it. "
                    "Send /linkgmail to link it again.",
                )
            return
        if emails:
            self._say(f"{len(emails)} new email(s) in {account.address}; checking.")
        for uid, raw in emails:
            try:
                if not await asyncio.to_thread(self._store.is_handled, account, uid):
                    outcome = (await self._handle(account, raw)).outcome
                    if outcome in (Outcome.RETRY, Outcome.LINK_CHANGED):
                        return
                if not await asyncio.to_thread(self._store.advance_cursor, account, uid):
                    return
            except (AssessmentError, OSError, ValueError):
                self._say("Could not save Gmail progress. Will retry.")
                return

    async def check_unread(self, chat_id: int) -> str:
        """Assess every unread email now (newest few), and return a summary reply."""
        try:
            account = await asyncio.to_thread(self._store.get, chat_id)
        except (AssessmentError, OSError, ValueError):
            return "Could not read the Gmail link. Please try again."
        if account is None:
            return "No Gmail is linked to this chat. Send /linkgmail first."
        mailbox = self._mailbox_factory(account.address, account.password)
        try:
            emails = await asyncio.to_thread(mailbox.unread, MANUAL_LIMIT)
        except MailboxError as error:
            return (
                "Could not reach Gmail. Please try again shortly."
                if error.retryable else
                "Gmail rejected the saved login. Send /linkgmail to link it again."
            )
        if not emails:
            return "No unread emails to check."
        counts = {"flagged": 0, "clean": 0, "skipped": 0, "retry": 0}
        done = []
        for uid, raw in emails:
            handled = await self._handle(account, raw)
            if handled.outcome is Outcome.LINK_CHANGED:
                return "Gmail link changed during the check. Run /checkmail again."
            if handled.outcome is Outcome.RETRY:
                counts["retry"] += 1
                continue
            done.append(uid)
            if handled.outcome is Outcome.DROP:
                counts["skipped"] += 1
            else:
                counts["flagged" if handled.flagged else "clean"] += 1
        # Never move the shared cursor: the poller has not seen the mail between it and
        # these UIDs. It skips exactly these UIDs and advances over them itself.
        try:
            if done and not await asyncio.to_thread(self._store.mark_handled, account, done):
                return "Gmail link changed during the check. Run /checkmail again."
        except (AssessmentError, OSError, ValueError):
            return "Could not save Gmail progress. Please try again."
        reply = (
            f"Checked {len(emails)} unread email(s): {counts['flagged']} flagged, "
            f"{counts['clean']} looked fine"
        )
        if counts["skipped"]:
            reply += f", {counts['skipped']} skipped"
        if counts["retry"]:
            reply += f". {counts['retry']} could not be checked right now (try again soon)"
        return reply + "."

    async def _handle(self, account: LinkedAccount, raw: bytes) -> Handled:
        """Assess one email. Failures become outcomes; nothing escapes this call."""
        try:
            return await self._assess_email(account, raw)
        except Exception as error:  # Unknown failures are not provably permanent.
            AppLogging.log_failure(logger, "Unexpected error while checking an email")
            self._say(f"An email failed with an unexpected error ({type(error).__name__}); "
                      "will retry.")
            return Handled(Outcome.RETRY)

    async def _assess_email(self, account: LinkedAccount, raw: bytes) -> Handled:
        key = (account.chat_id, account.link_id, hashlib.sha256(raw).hexdigest())
        pending = self._pending.get(key)
        if pending is None:
            prepared = await self._prepare(raw)
            if isinstance(prepared, Handled):
                return prepared
            pending = self._pending[key] = prepared
        try:
            if not await asyncio.to_thread(self._store.is_current, account):
                self._pending.pop(key, None)
                return Handled(Outcome.LINK_CHANGED)
        except (AssessmentError, OSError, ValueError):
            AppLogging.log_failure(logger, "Could not verify the Gmail link is still active")
            return Handled(Outcome.RETRY)
        if not pending.saved:
            try:
                async with self._save_lock:
                    await asyncio.to_thread(self._data_manager.save, pending.report)
                pending.saved = True
            except (AssessmentError, OSError, ValueError):
                AppLogging.log_failure(logger, "Could not save an email report")
                self._say("Could not save the email report; will retry.")
                return Handled(Outcome.RETRY)
        result = pending.result
        alert = result["priority"] in ALERT_PRIORITIES
        if alert:
            source = EmailSource(raw)
            text = self._formatter.format(
                result, pending.sender, source.subject, source.gmail_url(account.address)
            )
            reply_markup = (
                FeedbackKeyboardFactory.assessment_feedback_keyboard(result["assessment_id"])
                if self._feedback_service is not None
                else None
            )
            # An unlink may have landed since the check above; it revokes the link
            # before deleting it and waits for this lock, so nothing is sent after it
            # returns, and nothing is sent if it got there first.
            async with self._store.delivery(account.chat_id):
                try:
                    if not await asyncio.to_thread(self._store.is_current, account):
                        self._pending.pop(key, None)
                        return Handled(Outcome.LINK_CHANGED)
                except (AssessmentError, OSError, ValueError):
                    AppLogging.log_failure(
                        logger, "Could not verify the Gmail link is still active"
                    )
                    return Handled(Outcome.RETRY)
                delivered = await self._send(
                    account.chat_id, text, reply_markup=reply_markup
                )
            if not delivered:
                self._say("Could not send the alert; will retry.")
                return Handled(Outcome.RETRY)
        self._pending.pop(key, None)
        self._say(
            f"Checked an email: priority {result['priority']}" + (", alert sent." if alert else ".")
        )
        return Handled(Outcome.SENT, flagged=alert)

    async def _prepare(self, raw: bytes) -> _Pending | Handled:
        """Parse and assess an email; return a DROP or RETRY outcome if that fails."""
        try:
            sender, text = self._reader.read_bytes(raw)
        except ValueError:
            AppLogging.log_failure(logger, "Skipped an unreadable email")
            self._say("Skipped an email that could not be read.")
            return Handled(Outcome.DROP)
        try:
            record = {**self._builder.build(text, sender), "channel": "email"}
        except (InvalidInput, ValueError):
            self._say("Skipped an email that could not be read.")
            return Handled(Outcome.DROP)
        except OSError:
            self._say("Could not prepare an email; will retry.")
            return Handled(Outcome.RETRY)
        try:
            result = await asyncio.to_thread(self._assessment.assess, record)
        except InvalidInput:
            AppLogging.log_failure(logger, "Skipped an email the AI could not assess")
            self._say("Skipped an email the AI could not assess.")
            return Handled(Outcome.DROP)
        except AssessmentError as error:
            AppLogging.log_failure(logger, "Email assessment failed after AI retries")
            self._say(f"AI check failed, will retry: {self._errors.translate(error)}")
            return Handled(Outcome.RETRY)
        return _Pending(record, result, sender, self._assessment.build_report(record, result))

    async def _send(self, chat_id: int, text: str, reply_markup=None) -> bool:
        """Send a Telegram message. Return whether Telegram accepted it."""
        try:
            options = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": ParseMode.HTML,
                "disable_web_page_preview": True,
            }
            if reply_markup is not None:
                options["reply_markup"] = reply_markup
            await self._bot.send_message(**options)
        except Exception:
            AppLogging.log_failure(logger, "Could not send a Telegram alert")
            return False
        return True
