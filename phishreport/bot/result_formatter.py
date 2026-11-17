"""Format assessment results and the compact Telegram exposure card."""

from phishreport.bot.exposure import ExposureSession
from phishreport.io.plain_text_renderer import PlainTextRenderer
from phishreport.io.render import AssessmentRenderer
from phishreport.model import AssessmentResult

MAX_REPLY_CHARS = 4000  # Telegram rejects messages longer than 4096 characters.


def _bounded(text: str, suffix: str = "") -> str:
    """Fit text and its suffix into Telegram's UTF-16 reply limit."""
    # Telegram's UTF-16 limit counts non-BMP characters as two units.
    budget = MAX_REPLY_CHARS - len(suffix.encode("utf-16-le")) // 2
    encoded = text.encode("utf-16-le")
    if len(encoded) // 2 > budget:
        text = encoded[: (budget - 3) * 2].decode("utf-16-le", errors="ignore") + "..."
    return text + suffix


class ResultFormatter:
    """Format an evaluated outcome as the text of a chat reply."""

    FOOTER = "A low priority result does not guarantee that a message is safe."

    def __init__(self) -> None:
        self._assessment_renderer = AssessmentRenderer()
        self._text_renderer = PlainTextRenderer()

    def format(
        self, result: AssessmentResult | dict | None, *, session: ExposureSession | None = None,
    ) -> str:
        """Render the full console text, or the saved assessment card for Telegram.

        The card keeps the priority, score, matched rule, reasons and recommended
        actions. It leaves out the rule trace, provisional notes and disclaimers
        so one pasted message produces one short reply.
        """
        if session is not None:
            return _bounded(self._card(session.result))
        text = self._text_renderer.render(self._assessment_renderer.render(result))
        return _bounded(text, "\n\n" + self.FOOTER)

    def _card(self, result: AssessmentResult | dict | None) -> str:
        """Render the reply for a session that is already saved."""
        document = self._assessment_renderer.render(result)
        if not document.available:
            return "No assessment available."
        lines = []
        for kind, title, entries in document.sections:
            if kind == "fields":
                for label, value in entries:
                    if label == "Priority":
                        value = (value or "unavailable").replace("_", " ").title()
                    elif label == "Rule-based score" and value is None:
                        value = "Unavailable"
                    lines.append(f"{label}: {value}")
                continue
            if kind == "trace":
                continue
            lines.extend(("", f"{title}:"))
            if kind == "bullets":
                lines.extend(f"- {value}" for _, value in entries)
            elif kind == "numbered":
                lines.extend(
                    f"{number}. {value}"
                    for number, (_, value) in enumerate(entries, start=1)
                )
        return "\n".join(lines)
