"""Telegram keyboard helpers and message formatter compatibility exports."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from phishreport.bot.alert_formatter import PhishingAlertFormatter
from phishreport.bot.chat_record_builder import ChatRecordBuilder
from phishreport.bot.exposure import CANCEL_ACTION, CONFIRM_ACTION, ExposureSession
from phishreport.bot.result_formatter import MAX_REPLY_CHARS, ResultFormatter

EXPOSURE_CALLBACK_PREFIX = "exposure"
CONFIRMATION_PROMPT = "Check this message?"
CONFIRMATION_WARNING = "This text is sent to the AI provider for analysis."
CONFIRMATION_YES = "Yes, check it"
CONFIRMATION_CANCEL = "Cancel"
CONFIRMATION_CANCELLED = "Cancelled. Nothing was sent or saved."
CONFIRMATION_EXPIRED = "This confirmation expired. Paste the message again."
CONFIRMATION_PREVIEW_CHARS = 400


def confirmation_preview(text: str) -> str:
    """Quote at most 400 characters, marking any cut with a trailing ellipsis."""
    if len(text) <= CONFIRMATION_PREVIEW_CHARS:
        return text
    return text[:CONFIRMATION_PREVIEW_CHARS] + "..."


def build_confirmation_card(text: str) -> str:
    """Render the exact text before it is sent to the AI provider."""
    return (
        f"{CONFIRMATION_PROMPT}\n\n"
        f'"{confirmation_preview(text)}"\n\n'
        f"{CONFIRMATION_WARNING}"
    )


def build_confirmation_keyboard(token: str) -> InlineKeyboardMarkup:
    """Ask for one explicit yes or no before any assessment work starts."""
    def button(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            label, callback_data=f"{EXPOSURE_CALLBACK_PREFIX}:{token}:{action}"
        )

    return InlineKeyboardMarkup(
        [[button(CONFIRMATION_YES, CONFIRM_ACTION),
          button(CONFIRMATION_CANCEL, CANCEL_ACTION)]]
    )


def build_exposure_keyboard(session: ExposureSession) -> InlineKeyboardMarkup | None:
    """Render the two follow-up answers and the dismissal without changing state."""
    if session.dismissed or not session.saved:
        return None

    def button(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            label, callback_data=f"{EXPOSURE_CALLBACK_PREFIX}:{session.token}:{action}"
        )

    rows = [[button("Clicked link", "clicked"),
             button("Shared a password/OTP", "password")]]
    if not session.answered:
        rows.append([button("Nothing happened", "nothing")])
    return InlineKeyboardMarkup(rows)


__all__ = [
    "MAX_REPLY_CHARS",
    "EXPOSURE_CALLBACK_PREFIX",
    "CONFIRMATION_PROMPT",
    "CONFIRMATION_WARNING",
    "CONFIRMATION_YES",
    "CONFIRMATION_CANCEL",
    "CONFIRMATION_CANCELLED",
    "CONFIRMATION_EXPIRED",
    "CONFIRMATION_PREVIEW_CHARS",
    "ChatRecordBuilder",
    "PhishingAlertFormatter",
    "ResultFormatter",
    "build_confirmation_card",
    "build_confirmation_keyboard",
    "build_exposure_keyboard",
    "confirmation_preview",
]
