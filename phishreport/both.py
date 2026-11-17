"""Run the interactive CLI and the Telegram bot from one process."""

import asyncio
import logging
import os
import sys
import threading
from collections.abc import Callable

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from phishreport.ai import AIManager
from phishreport.assessment import AssessmentService
from phishreport.bot.gmail import AccountStore
from phishreport.bot.gmail_handlers import GmailLinkHandlers
from phishreport.bot.handlers import CHECK_CONNECTION, TelegramIOManager
from phishreport.bot.main import COMMANDS, startup_guide
from phishreport.bot.messages import EXPOSURE_CALLBACK_PREFIX, ChatRecordBuilder
from phishreport.bot.monitor import EmailMonitor
from phishreport.cli.main import EnvLoader, PhishReportApp
from phishreport.data import DataManager, ReportStorage
from phishreport.data.factory import create_report_storage
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.io import IOManager
from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager

logger = AppLogging.get_logger(__name__)


def _write_line(stream, text: str) -> None:
    """Write and flush one complete line without owning terminal input."""
    stream.write(f"{text}\n")
    stream.flush()


class LockedDataManager(DataManager):
    """Serialize report reads and read-modify-write saves across threads.

    The bot's asyncio lock only orders coroutines inside its own event loop;
    this lock also orders bot saves against the CLI running on the main thread.
    """

    def __init__(self, storage=None, validator=None, lock=None) -> None:
        super().__init__(storage, validator)
        self._lock = threading.RLock() if lock is None else lock

    @property
    def lock(self):
        """Return the lock that guards every save and load."""
        return self._lock

    def save(self, record: dict) -> None:
        """Append one report while holding the shared data lock."""
        with self._lock:
            super().save(record)

    def load(self, *, strict: bool = False) -> list[dict]:
        """Read history while holding the shared data lock."""
        with self._lock:
            return super().load(strict=strict)


class BotThread(threading.Thread):
    """Run a bot worker on a daemon thread and surface any failure."""

    def __init__(self, worker: Callable[[threading.Event], None]) -> None:
        super().__init__(daemon=True, name="phishreport-bot")
        self._worker = worker
        self._stop_event = threading.Event()
        self.failure: BaseException | None = None

    def run(self) -> None:
        try:
            self._worker(self._stop_event)
        except BaseException as error:
            self.failure = error
            AppLogging.log_failure(logger, "Telegram bot stopped unexpectedly")
            _write_line(
                sys.stderr,
                "Telegram bot stopped unexpectedly; the CLI is still running.",
            )

    def stop(self, timeout: float = 10.0) -> None:
        """Ask the bot loop to finish, then wait for its thread."""
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)


class BothApp:
    """Run the bot on a daemon thread while the CLI owns the main thread."""

    def __init__(
        self,
        bot_worker: Callable[[threading.Event], None],
        cli_loop: Callable[[], None],
        *,
        stop_timeout: float = 10.0,
    ) -> None:
        self._bot_worker = bot_worker
        self._cli_loop = cli_loop
        self._stop_timeout = stop_timeout

    def run(self) -> int:
        """Start both adapters, then stop the bot when the CLI loop ends."""
        bot = BotThread(self._bot_worker)
        bot.start()
        try:
            self._cli_loop()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            bot.stop(self._stop_timeout)
        return 0


def build_shared_manager(
    storage: ReportStorage | None = None,
    *,
    lock=None,
) -> LockedDataManager:
    """Create the single report manager shared by the CLI and bot.

    SQLite is the default because two threads write the same history; an
    explicit PHISHREPORT_STORAGE value still selects the requested backend.
    """
    os.environ.setdefault("PHISHREPORT_STORAGE", "sqlite")
    if storage is None:
        storage = create_report_storage()
    return LockedDataManager(storage, lock=lock)


def build_cli_app(data_manager: DataManager) -> PhishReportApp:
    """Build the unchanged CLI workflows around the shared report manager."""
    return PhishReportApp(
        io_manager=IOManager(ConsoleTerminal()),
        ai_manager=AIManager(),
        logic_manager=LogicManager(),
        data_manager=data_manager,
        feedback_service=FeedbackService(
            FeedbackStore(os.environ.get("PHISHREPORT_FEEDBACK_PATH", "feedback.json"))
        ),
    )


def build_bot_application(
    data_manager: DataManager,
    token: str,
    allowed_chat_id: int | None = None,
) -> Application:
    """Build the polling application around the shared report manager."""
    assessment = AssessmentService(AIManager(), LogicManager())
    feedback_service = FeedbackService(
        FeedbackStore(os.environ.get("PHISHREPORT_FEEDBACK_PATH", "feedback.json"))
    )
    manager = TelegramIOManager(
        data_manager,
        allowed_chat_id,
        assessment=assessment,
        feedback_service=feedback_service,
    )
    store = AccountStore(os.environ.get("PHISHREPORT_GMAIL_PATH", "gmail_accounts.json"))
    gmail = GmailLinkHandlers(store, manager.is_allowed)

    async def start_monitor(application: Application) -> None:
        builder = ChatRecordBuilder()
        catalog = discover_commands(CommandCapabilities(
            prepare_record=lambda request: builder.build(request.text),
            assess_record=assessment.assess_with_findings,
            session_status=lambda request: "Telegram startup",
            report_count=lambda: len(data_manager.load(strict=True)),
        ))
        entries = list(COMMANDS)
        names = {entry.command for entry in entries}
        for command in catalog:
            if command.name in names:
                raise ValueError(f"Shared command conflicts with native command: {command.name}")
            if len(command.name) > 32:
                raise ValueError("Telegram command names must contain at most 32 characters.")
            if not isinstance(command.help_text, str) or not 1 <= len(command.help_text) <= 256:
                raise ValueError("Telegram command descriptions must contain 1-256 characters.")
            entries.append(BotCommand(command.name, command.help_text))
            names.add(command.name)
        if len(entries) > 100:
            raise ValueError("Telegram supports at most 100 menu commands.")
        await application.bot.set_my_commands(entries)
        monitor = EmailMonitor(
            application.bot,
            store,
            assessment,
            data_manager,
            manager.save_lock,
            feedback_service=feedback_service,
        )
        application.bot_data["monitor"] = monitor
        application.bot_data["monitor_task"] = asyncio.create_task(monitor.run())
        _write_line(sys.stdout, startup_guide(application.bot.username))

    async def stop_monitor(application: Application) -> None:
        task = application.bot_data.get("monitor_task")
        if task is not None:
            task.cancel()

    # Telegram library diagnostics can contain the token in request URLs.
    logging.getLogger("telegram").setLevel(logging.CRITICAL + 1)
    # Mirror the bot launcher so both entry points expose the same commands.
    application = (
        Application.builder()
        .token(token)
        .post_init(start_monitor)
        .post_shutdown(stop_monitor)
        .build()
    )
    application.add_handler(CommandHandler("start", manager.start))
    application.add_handler(CommandHandler("linkgmail", gmail.link))
    application.add_handler(CommandHandler("checkmail", gmail.check))
    application.add_handler(CommandHandler("unlinkgmail", gmail.unlink))
    application.add_handler(
        CallbackQueryHandler(manager.check_connection, pattern=rf"^{CHECK_CONNECTION}\Z")
    )
    application.add_handler(
        CallbackQueryHandler(manager.handle_feedback_callback, pattern=r"^fb:")
    )
    application.add_handler(
        CallbackQueryHandler(
            manager.exposure_callback, pattern=rf"^{EXPOSURE_CALLBACK_PREFIX}:", block=False
        )
    )
    application.add_handler(
        MessageHandler(filters.TEXT, manager.assess_message, block=False)
    )
    application.add_error_handler(_report_polling_error)
    return application


async def _report_polling_error(update, context) -> None:
    """Keep Telegram request URLs and update contents out of diagnostics."""
    _write_line(
        sys.stderr,
        "A Telegram request failed. Check the bot connection and try again.",
    )


async def _poll_until_stopped(application: Application, stop_event: threading.Event) -> None:
    """Initialize polling, wait for the stop event, then shut down in order."""
    try:
        await application.initialize()
        if application.post_init is not None:
            await application.post_init(application)
        if stop_event.is_set():
            return
        updater = application.updater
        if updater is None:
            raise RuntimeError("Telegram application has no updater.")
        await updater.start_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
        await application.start()
        while not stop_event.is_set():
            await asyncio.sleep(0.2)
    finally:
        updater = application.updater
        if updater is not None and updater.running:
            await updater.stop()
        if application.running:
            await application.stop()
            if application.post_stop is not None:
                await application.post_stop(application)
        await application.shutdown()
        if application.post_shutdown is not None:
            await application.post_shutdown(application)


def _bot_worker(application: Application, stop_event: threading.Event) -> None:
    """Run the application's polling loop on this thread's own event loop."""
    asyncio.run(_poll_until_stopped(application, stop_event))


def _parse_allowed_chat_id(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    chat_id = int(raw)
    if chat_id <= 0:
        raise ValueError
    return chat_id


def main() -> int:
    """Compose one storage backend, one manager and both adapters."""
    EnvLoader().load()
    if not AppLogging.setup():
        _write_line(sys.stderr, "Warning: diagnostic logging is unavailable.")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        _write_line(sys.stderr, "Set TELEGRAM_BOT_TOKEN to the existing bot token.")
        return 1
    try:
        allowed_chat_id = _parse_allowed_chat_id(
            os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
        )
    except ValueError:
        _write_line(
            sys.stderr,
            "TELEGRAM_ALLOWED_CHAT_ID must be a positive private chat ID, or blank.",
        )
        return 1

    data_manager = build_shared_manager()
    application = build_bot_application(data_manager, token, allowed_chat_id)
    cli_app = build_cli_app(data_manager)

    def bot_worker(stop_event: threading.Event) -> None:
        _bot_worker(application, stop_event)

    return BothApp(bot_worker, cli_app.run).run()


if __name__ == "__main__":
    raise SystemExit(main())
