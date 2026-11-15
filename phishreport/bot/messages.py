"""Telegram keyboard helpers and message formatter compatibility exports."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from phishreport.bot.alert_formatter import PhishingAlertFormatter
from phishreport.bot.chat_record_builder import ChatRecordBuilder
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.result_formatter import MAX_REPLY_CHARS, ResultFormatter

EXPOSURE_CALLBACK_PREFIX = "exposure"


def build_exposure_keyboard(session: ExposureSession) -> InlineKeyboardMarkup | None:
    """Render explicit exposure answers and save actions without changing state."""
    if session.saved:
        return None
    if session.completed:
        return InlineKeyboardMarkup([[InlineKeyboardButton(
            "Retry saving", callback_data=f"{EXPOSURE_CALLBACK_PREFIX}:{session.token}:retry"
        )]])

    selected = set()
    clicked = session.exposure["clicked"]
    downloaded = session.exposure["downloaded"]
    if type(clicked) is bool and type(downloaded) is bool:
        selected.add({
            (True, False): "clicked",
            (False, True): "downloaded",
            (True, True): "both",
            (False, False): "neither",
        }[(clicked, downloaded)])
    if session.exposure["disclosure_answered"] is True:
        category = session.exposure["submitted_category"]
        if category in ("password", "otp"):
            selected.add(category)
        elif category is None:
            selected.add("no_disclosure")

    rows = [
        [("clicked", "Clicked link"), ("downloaded", "Downloaded file")],
        [("both", "Both"), ("neither", "Neither")],
        [("password", "Password"), ("otp", "One-time code")],
        [("no_disclosure", "Neither password nor code")],
        [("finish", "Finish and save"), ("skip", "Skip unanswered")],
    ]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✓ {label}" if action in selected else label,
            callback_data=f"{EXPOSURE_CALLBACK_PREFIX}:{session.token}:{action}",
        ) for action, label in row]
        for row in rows
    ])


__all__ = [
    "MAX_REPLY_CHARS",
    "EXPOSURE_CALLBACK_PREFIX",
    "ChatRecordBuilder",
    "PhishingAlertFormatter",
    "ResultFormatter",
    "build_exposure_keyboard",
]
