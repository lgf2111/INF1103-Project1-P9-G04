"""Build assessment records from chat text and format results as chat replies."""

from html import escape

from phishreport.io.presenter import ReportPresenter

MAX_REPLY_CHARS = 4000  # Telegram rejects messages longer than 4096 characters.


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

    def build(self, text: str, sender: str | None = None) -> dict:
        # A chat message carries no attachment details, and nothing is reported as
        # clicked, downloaded or submitted, so the rule-based score uses only the AI
        # findings.
        return {
            "channel": "chat",
            "sender": sender,
            "message": text,
            "has_link": False,
            "link": None,
            "has_file": False,
            "file_name": None,
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
