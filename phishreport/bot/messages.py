"""Build assessment records from chat text and format results as chat replies."""

import re
from html import escape

from phishreport.io.presenter import ReportPresenter

MAX_REPLY_CHARS = 4000  # Telegram rejects messages longer than 4096 characters.

# A pasted message can contain a bare URL; keep the first one so the record can
# report a link the user was asked to visit.
LINK_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?)]}\"'"


def first_link(text: str | None) -> str | None:
    """Return the first http(s) link in the text, without trailing punctuation."""
    if not text:
        return None
    match = LINK_PATTERN.search(text)
    if match is None:
        return None
    link = match.group(0).rstrip(TRAILING_PUNCTUATION)
    return link or None


def apply_exposure(record: dict, choice: str) -> dict:
    """Return a copy of the record with the user's exposure answer applied."""
    updated = {**record}
    if choice == "interacted":
        updated["clicked"] = True
    elif choice in ("password", "otp"):
        updated["submitted_category"] = choice
    return updated


def exposure_note(choice: str) -> str:
    """Describe what the recorded answer changed, for the reply text."""
    if choice == "interacted":
        return "\n\nExposure recorded: you said you clicked or downloaded something."
    if choice == "password":
        return "\n\nExposure recorded: you said you entered a password."
    if choice == "otp":
        return "\n\nExposure recorded: you said you entered a one-time code."
    return "\n\nNo exposure reported: the score uses the AI findings only."



class BufferTerminal:
    """Terminal that collects output as text instead of printing it.

    It satisfies the same Terminal contract as the console, so the existing
    ReportPresenter can format a result for a chat reply without any change.
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    def read(self, prompt: str) -> str:
        raise EOFError("A chat reply cannot ask for more input.")

    def write(self, *parts: object) -> None:
        self._lines.append(" ".join(str(part) for part in parts))

    def text(self) -> str:
        return "\n".join(self._lines).strip()


class ChatRecordBuilder:
    """Turn the text of a chat message into the record the managers expect."""

    def build(self, text: str, sender: str | None = None, document=None) -> dict:
        """Build a chat record, keeping link and file details the message carries.

        A chat message reports no clicks, downloads or shared credentials by itself,
        so those stay unset until the user answers the exposure question.
        """
        link = first_link(text)
        file_name = getattr(document, "file_name", None) if document is not None else None
        return {
            "channel": "chat",
            "sender": sender,
            "message": text,
            "has_link": link is not None,
            "link": link,
            "has_file": document is not None,
            "file_name": file_name,
            "clicked": False,
            "downloaded": False,
            "submitted_category": None,
        }


class ResultFormatter:
    """Format an evaluated outcome as the text of a chat reply."""

    FOOTER = "A low priority result does not guarantee that a message is safe."

    def format(self, result: dict) -> str:
        terminal = BufferTerminal()
        ReportPresenter(terminal).display_result(result)
        text = terminal.text()
        if len(text) > MAX_REPLY_CHARS:
            text = text[: MAX_REPLY_CHARS - 3] + "..."
        return f"{text}\n\n{self.FOOTER}"


class PhishingAlertFormatter:
    """Format a flagged email as a Telegram HTML message (parse_mode="HTML")."""

    BADGES = {"HIGH": "🚨 <b>HIGH risk</b>", "MEDIUM": "⚠️ <b>MEDIUM risk</b>"}
    MAX_LINE = 300
    MAX_STEPS = 5

    def _clip(self, text: str) -> str:
        text = " ".join(str(text).split())
        return escape(text if len(text) <= self.MAX_LINE else text[: self.MAX_LINE - 3] + "...")

    def format(
        self, result: dict, sender: str | None, subject: str = "", source_url: str | None = None
    ) -> str:
        priority = result.get("priority", "")
        lines = [
            f"{self.BADGES.get(priority, '⚠️ <b>Possible phishing</b>')} · possible phishing email",
            "",
            f"<b>From:</b> {self._clip(sender or 'Unknown sender')}",
        ]
        if subject:
            lines.append(f"<b>Subject:</b> {self._clip(subject)}")
        lines.append(f"<b>Score:</b> {escape(str(result.get('score', 'n/a')))}/100")
        if result.get("reasons"):
            lines += ["", "<b>Why it was flagged</b>"]
            lines += [f"• {self._clip(reason)}" for reason in result["reasons"]]
        steps = result.get("checklist", [])[: self.MAX_STEPS]
        if steps:
            lines += ["", "<b>What to do</b>"]
            lines += [f"{number}. {self._clip(step)}" for number, step in enumerate(steps, 1)]
        if source_url:
            lines += [
                "",
                f'📧 <a href="{escape(source_url, quote=True)}">Open the email in Gmail</a>',
            ]
        lines += ["", "<i>Do not click links or reply. A low score never guarantees safety.</i>"]
        return "\n".join(lines)
