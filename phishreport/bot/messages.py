"""Telegram keyboard helpers and message formatter compatibility exports."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from phishreport.bot.alert_formatter import PhishingAlertFormatter
from phishreport.bot.chat_record_builder import ChatRecordBuilder
from phishreport.bot.exposure import CANCEL_ACTION, CONFIRM_ACTION, ExposureSession
from phishreport.bot.result_formatter import (
    EXPOSURE_SAVED,
    MAX_REPLY_CHARS,
    ResultFormatter,
)

EXPOSURE_CALLBACK_PREFIX = "exposure"
EXPOSURE_ALREADY_SAVED = "Already saved."
EXPOSURE_EXPIRED = (
    "This assessment expired. Paste the message again to start a new assessment."
)
CONFIRMATION_PROMPT = "Check this message?"
CONFIRMATION_WARNING = "This text is sent to the AI provider for analysis."
CONFIRMATION_YES = "Yes, check it"
CONFIRMATION_CANCEL = "Cancel"
CONFIRMATION_CANCELLED = "Cancelled. Nothing was sent or saved."
CONFIRMATION_EXPIRED = "This confirmation expired. Paste the message again."
CONFIRMATION_PREVIEW_CHARS = 400

STATUS_CALLBACK_PREFIX = "status"
STATUS_CSV_CALLBACK = "status:csv"
STATUS_SUMMARY_CALLBACK = "status:summary"
STATUS_CSV_LABEL = "Download all reports (CSV)"
STATUS_SUMMARY_LABEL = "Download summary (TXT)"
STATUS_NOTHING_SAVED = "Nothing saved yet."
STATUS_DOWNLOAD_FAILED = "Could not prepare the download. Please try again."


class MessageFactory:
    """Build the Telegram cards, keyboards and documents shown to the user."""

    @staticmethod
    def confirmation_preview(text: str) -> str:
        """Quote at most 400 characters, marking any cut with a trailing ellipsis."""
        if len(text) <= CONFIRMATION_PREVIEW_CHARS:
            return text
        return text[:CONFIRMATION_PREVIEW_CHARS] + "..."

    @staticmethod
    def build_confirmation_card(text: str) -> str:
        """Render the exact text before it is sent to the AI provider."""
        return (
            f"{CONFIRMATION_PROMPT}\n\n"
            f'"{MessageFactory.confirmation_preview(text)}"\n\n'
            f"{CONFIRMATION_WARNING}"
        )

    @staticmethod
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

    @staticmethod
    def build_exposure_keyboard(session: ExposureSession) -> InlineKeyboardMarkup | None:
        """Render only the answers that can still change the result.

        A reported password reaches the top band, so that answer ends the card.
        After a reported click, only the password can raise the score further;
        "Nothing else" closes the card without another write.
        """
        if not session.saved or session.finished:
            return None

        def button(label: str, action: str) -> InlineKeyboardButton:
            return InlineKeyboardButton(
                label, callback_data=f"{EXPOSURE_CALLBACK_PREFIX}:{session.token}:{action}"
            )

        if session.exposure["clicked"] is True:
            rows = [[button("Shared a password/OTP", "password"),
                     button("Nothing else", "nothing")]]
        else:
            rows = [[button("Clicked link", "clicked"),
                     button("Shared a password/OTP", "password")],
                    [button("Nothing happened", "nothing")]]
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def build_status_keyboard(has_reports: bool) -> InlineKeyboardMarkup | None:
        """Offer the two downloads in one row, only when history has a report."""
        if not has_reports:
            return None
        return InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(STATUS_CSV_LABEL, callback_data=STATUS_CSV_CALLBACK),
                InlineKeyboardButton(
                    STATUS_SUMMARY_LABEL, callback_data=STATUS_SUMMARY_CALLBACK,
                ),
            ]]
        )

    @staticmethod
    def build_summary_document(summary, description: str = "all reports") -> str:
        """Render the CLI summary as a text document with the same sections."""
        lines = [
            "=== Report summary ===",
            f"Showing: {description}",
            f"Reports: {summary.total}",
        ]
        if summary.total == 0:
            lines.append("No saved reports match.")
            return "\n".join(lines) + "\n"
        for section in summary.sections:
            lines.append("")
            lines.append(f"{section.title}:")
            lines.extend(f" - {label}: {value}" for label, value in section.rows)
        return "\n".join(lines) + "\n"


__all__ = [
    "MAX_REPLY_CHARS",
    "EXPOSURE_CALLBACK_PREFIX",
    "EXPOSURE_ALREADY_SAVED",
    "EXPOSURE_EXPIRED",
    "EXPOSURE_SAVED",
    "CONFIRMATION_PROMPT",
    "CONFIRMATION_WARNING",
    "CONFIRMATION_YES",
    "CONFIRMATION_CANCEL",
    "CONFIRMATION_CANCELLED",
    "CONFIRMATION_EXPIRED",
    "CONFIRMATION_PREVIEW_CHARS",
    "STATUS_CALLBACK_PREFIX",
    "STATUS_CSV_CALLBACK",
    "STATUS_SUMMARY_CALLBACK",
    "STATUS_CSV_LABEL",
    "STATUS_SUMMARY_LABEL",
    "STATUS_NOTHING_SAVED",
    "STATUS_DOWNLOAD_FAILED",
    "ChatRecordBuilder",
    "PhishingAlertFormatter",
    "MessageFactory",
    "ResultFormatter",
]
