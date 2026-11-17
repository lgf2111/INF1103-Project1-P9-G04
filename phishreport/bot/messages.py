"""Telegram keyboard helpers and message formatter compatibility exports."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from phishreport.bot.alert_formatter import PhishingAlertFormatter
from phishreport.bot.chat_record_builder import ChatRecordBuilder
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.result_formatter import MAX_REPLY_CHARS, ResultFormatter

EXPOSURE_CALLBACK_PREFIX = "exposure"


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
    "ChatRecordBuilder",
    "PhishingAlertFormatter",
    "ResultFormatter",
    "build_exposure_keyboard",
]
