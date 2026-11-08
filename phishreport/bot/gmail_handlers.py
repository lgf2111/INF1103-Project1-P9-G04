"""Telegram commands that link or unlink a Gmail account."""

import asyncio
from collections.abc import Callable

from telegram import Update
from telegram.ext import ContextTypes

from phishreport.bot.gmail import AccountStore, GmailMailbox, LinkedAccount, MailboxError

LINK_HELP = (
    "Link your Gmail so I can check new emails for phishing.\n\n"
    "1. Turn on 2-Step Verification for your Google account.\n"
    "2. Create an app password at https://myaccount.google.com/apppasswords\n"
    "3. Send: /linkgmail you@gmail.com your app password\n\n"
    "I delete your message once it is read and only look at unread mail that "
    "arrives after linking. Use /unlinkgmail to stop."
)


class GmailLinkHandlers:
    """Handle /linkgmail and /unlinkgmail in a private chat."""

    def __init__(
        self,
        store: AccountStore,
        is_allowed: Callable[[Update], bool],
        mailbox_factory: Callable[[str, str], GmailMailbox] = GmailMailbox,
    ) -> None:
        self._store = store
        self._is_allowed = is_allowed
        self._mailbox_factory = mailbox_factory

    async def link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not self._is_allowed(update) or message is None:
            return
        args = list(context.args or [])
        if len(args) < 2:
            await message.reply_text(LINK_HELP)
            return

        address = args[0].strip().lower()
        password = "".join(args[1:])  # Google shows app passwords in groups with spaces.
        try:
            await message.delete()  # Do not leave the password in the chat history.
        except Exception:  # Deleting is best effort; linking can still continue.
            pass
        chat = update.effective_chat
        reply = chat.send_message if chat is not None else message.reply_text

        if not GmailMailbox.is_valid_address(address):
            await reply("That does not look like an email address. Try /linkgmail again.")
            return
        try:
            # Proves the login works and marks "now": only later mail is checked.
            newest = await asyncio.to_thread(self._mailbox_factory(address, password).latest_uid)
        except MailboxError as error:
            hint = " Check the app password (not your normal one)." if not error.retryable else ""
            await reply(f"{error}{hint}")
            return
        await asyncio.to_thread(self._store.save, LinkedAccount(chat.id, address, password, newest))
        await reply(
            f"Linked {address}. I will check new emails and message you here "
            "if one looks like phishing."
        )

    async def unlink(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if not self._is_allowed(update) or message is None or chat is None:
            return
        removed = await asyncio.to_thread(self._store.remove, chat.id)
        await message.reply_text(
            "Gmail unlinked and the saved app password deleted."
            if removed
            else "No Gmail account is linked to this chat."
        )
