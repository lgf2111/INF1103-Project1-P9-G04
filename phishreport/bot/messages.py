"""Build assessment records from chat text and format results as chat replies."""

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
