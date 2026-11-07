"""Render the Telegram welcome screen and check local history access."""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from app_cli.data_core import DataManager

CHECK_CONNECTION = "check_connection"


class TelegramIOManager:
    def __init__(self, data_manager: DataManager, allowed_chat_id: int) -> None:
        self._data_manager = data_manager
        self._allowed_chat_id = allowed_chat_id

    def _is_allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        return (
            chat is not None and chat.id == self._allowed_chat_id and chat.type == ChatType.PRIVATE
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not self._is_allowed(update) or message is None:
            return
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Check connection", callback_data=CHECK_CONNECTION)]]
        )
        await message.reply_text("Welcome to PhishReport.", reply_markup=keyboard)

    async def check_connection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        message = update.effective_message
        if not self._is_allowed(update) or query is None or message is None:
            return

        await query.answer()
        try:
            await asyncio.to_thread(self._data_manager.load, strict=True)
        except (OSError, ValueError):
            await message.reply_text("Could not read local history. Please try again.")
        else:
            await message.reply_text("Connection check passed.")
