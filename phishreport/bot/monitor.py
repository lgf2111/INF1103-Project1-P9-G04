"""Poll linked Gmail inboxes in the background and alert on phishing."""

import asyncio
from collections.abc import Callable

from telegram import Bot

from phishreport.ai.errors import AIErrorTranslator
from phishreport.bot.gmail import AccountStore, GmailMailbox, LinkedAccount, MailboxError
from phishreport.bot.messages import ChatRecordBuilder, ResultFormatter
from phishreport.io.eml import EmlReader
from phishreport.logging_setup import AppLogging

logger = AppLogging.get_logger("email_monitor")

ALERT_PRIORITIES = {"MEDIUM", "HIGH"}
POLL_SECONDS = 60


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
        formatter: ResultFormatter | None = None,
    ) -> None:
        self._bot = bot
        self._store = store
        self._assessment = assessment
        self._data_manager = data_manager
        self._save_lock = save_lock
        self._interval = interval
        self._mailbox_factory = mailbox_factory
        self._reader = reader or EmlReader()
        self._formatter = formatter or ResultFormatter()
        self._builder = ChatRecordBuilder()
        self._errors = AIErrorTranslator()

    @staticmethod
    def _say(text: str) -> None:
        """Show progress in the terminal. Never include email content or secrets."""
        print(f"[email] {text}", flush=True)

    async def run(self) -> None:
        """Poll forever; one failing cycle never stops the loop."""
        while True:
            try:
                await self.poll_once()
            except Exception:
                AppLogging.log_failure(logger, "Email polling cycle failed")
            self._say("Checking the inbox failed; will retry.")
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
            self._say(f"{error} {'Unlinked.' if not error.retryable else 'Will retry.'}")
            if not error.retryable:
                await asyncio.to_thread(self._store.remove, account.chat_id)
                await self._send(
                    account.chat_id,
                    "Gmail rejected the saved login, so I unlinked it. "
                    "Send /linkgmail to link it again.",
                )
            return
        if emails:
            self._say(f"{len(emails)} new email(s) in {account.address}; checking.")
        for uid, raw in emails:
            if not await self._handle(account, raw):
                return  # Temporary AI failure: keep this email and retry next cycle.
            account.last_uid = uid
            await asyncio.to_thread(self._store.save, account)

    async def _handle(self, account: LinkedAccount, raw: bytes) -> bool:
        """Assess one email. Return False if it should be retried later."""
        try:
            sender, text = self._reader.read_bytes(raw)
        except ValueError:
            AppLogging.log_failure(logger, "Skipped an unreadable email")
            self._say("Skipped an email that could not be read.")
            return True
        record = {**self._builder.build(text, sender), "channel": "email"}
        try:
            result = await asyncio.to_thread(self._assessment.assess, record)
        except RuntimeError as error:
            AppLogging.log_failure(logger, "Email assessment failed after AI retries")
            self._say(f"AI check failed, will retry: {self._errors.translate(error)}")
            return False
        except ValueError:
            AppLogging.log_failure(logger, "Skipped an email the AI could not assess")
            self._say("Skipped an email the AI could not assess.")
            return True
        try:
            async with self._save_lock:
                await asyncio.to_thread(
                    self._data_manager.save, self._assessment.build_report(record, result)
                )
        except (OSError, ValueError):
            AppLogging.log_failure(logger, "Could not save an email report")
        alert = result["priority"] in ALERT_PRIORITIES
        self._say(
            f"Checked an email: priority {result['priority']}" + (", alert sent." if alert else ".")
        )
        if alert:
            await self._send(
                account.chat_id,
                f"Possible phishing email from {sender or 'an unknown sender'}\n\n"
                + self._formatter.format(result),
            )
        return True

    async def _send(self, chat_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            AppLogging.log_failure(logger, "Could not send a Telegram alert")
