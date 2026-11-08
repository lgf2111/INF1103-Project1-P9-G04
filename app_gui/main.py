"""Start the PhishReport bot using outbound Telegram polling."""

import logging
import os
import sys

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from app_cli.data_core import DataManager, JsonReportStorage

from .telegram_io_manager import CHECK_CONNECTION, TelegramIOManager


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

    history_path = os.environ.get("PHISHREPORT_REPORTS_PATH", "reports.json")
    manager = TelegramIOManager(DataManager(JsonReportStorage(history_path)), chat_id)
    # Telegram library diagnostics can contain the token in request URLs.
    logging.getLogger("telegram").setLevel(logging.CRITICAL + 1)
    try:
        application = Application.builder().token(token).build()
        application.add_handler(CommandHandler("start", manager.start))
        application.add_handler(
            CallbackQueryHandler(manager.check_connection, pattern=rf"^{CHECK_CONNECTION}\Z")
        )
        application.add_error_handler(_report_polling_error)
        application.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY])
    except TelegramError:
        print("Could not start polling. Check the bot token and connection.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
