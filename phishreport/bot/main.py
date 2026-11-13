"""Start the PhishReport bot using outbound Telegram polling."""

import asyncio
import logging
import os
import sys

from telegram import BotCommand, Update
from telegram.error import TelegramError
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
from phishreport.bot.monitor import EmailMonitor
from phishreport.data import DataManager
from phishreport.data.factory import create_report_storage
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager

COMMANDS = [
    BotCommand("start", "Welcome and connection check"),
    BotCommand("linkgmail", "Link Gmail to watch for phishing emails"),
    BotCommand("checkmail", "Check all unread emails for phishing now"),
    BotCommand("unlinkgmail", "Unlink Gmail and delete the saved password"),
]


def startup_guide(username: str) -> str:
    """Tell whoever started the bot what to do next."""
    return (
        "\nPhishReport bot is running.\n"
        f"  1. Open Telegram and message @{username} (https://t.me/{username}).\n"
        "  2. Send /start, or paste any suspicious message to get an assessment.\n"
        "  3. Send /linkgmail to watch your Gmail. It needs a Google app password:\n"
        "     https://myaccount.google.com/apppasswords (2-Step Verification must be on).\n"
        "  4. Send /checkmail any time to check all unread emails right away.\n"
        "  5. After linking, new emails are checked every minute and you get a\n"
        "     Telegram message if one looks like phishing. Use /unlinkgmail to stop.\n"
        "Press Ctrl+C to stop the bot.\n"
    )


async def _report_polling_error(update, context):
    """Keep Telegram request URLs and update contents out of diagnostics."""
    print("A Telegram request failed. Check the bot connection and try again.", file=sys.stderr)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN to the existing bot token.", file=sys.stderr)
        return 1

    # A blank or unset ID accepts any private chat; a value restricts to that chat.
    chat_id = None
    raw_chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if raw_chat_id:
        try:
            chat_id = int(raw_chat_id)
            if chat_id <= 0:
                raise ValueError
        except ValueError:
            print(
                "TELEGRAM_ALLOWED_CHAT_ID must be a positive private chat ID, or blank.",
                file=sys.stderr,
            )
            return 1

    data_manager = DataManager(create_report_storage())
    assessment = AssessmentService(AIManager(), LogicManager())
    feedback_service = FeedbackService(
        FeedbackStore(os.environ.get("PHISHREPORT_FEEDBACK_PATH", "feedback.json"))
    )
    manager = TelegramIOManager(
        data_manager,
        chat_id,
        assessment=assessment,
        feedback_service=feedback_service,
    )
    store = AccountStore(os.environ.get("PHISHREPORT_GMAIL_PATH", "gmail_accounts.json"))
    gmail = GmailLinkHandlers(store, manager.is_allowed)
    AppLogging.setup()

    async def start_monitor(application: Application) -> None:
        await application.bot.set_my_commands(COMMANDS)
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
        print(startup_guide(application.bot.username), flush=True)

    async def stop_monitor(application: Application) -> None:
        task = application.bot_data.get("monitor_task")
        if task is not None:
            task.cancel()

    # Telegram library diagnostics can contain the token in request URLs.
    logging.getLogger("telegram").setLevel(logging.CRITICAL + 1)
    try:
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
            MessageHandler(filters.TEXT & ~filters.COMMAND, manager.assess_message)
        )
        application.add_error_handler(_report_polling_error)
        application.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
    except TelegramError:
        print("Could not start polling. Check the bot token and connection.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
