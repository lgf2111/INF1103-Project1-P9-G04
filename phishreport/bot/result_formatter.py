"""Format assessment results and exposure notices as Telegram text replies."""

from phishreport.bot.exposure import ExposureSession
from phishreport.io.plain_text_renderer import PlainTextRenderer
from phishreport.io.render import AssessmentRenderer

MAX_REPLY_CHARS = 4000  # Telegram rejects messages longer than 4096 characters.


class ResultFormatter:
    """Format an assessed outcome as a bounded Telegram text reply."""

    FOOTER = "A low priority result does not guarantee that a message is safe."

    def __init__(self) -> None:
        self._assessment_renderer = AssessmentRenderer()
        self._text_renderer = PlainTextRenderer()

    def format(self, result: dict, *, session: ExposureSession | None = None) -> str:
        """Render current or frozen exposure answers, reserving mandatory notices."""
        notices = []
        if session is not None:
            result = session.result
            exposure = session.exposure
            if (session.completed or session.saved) and session.report is not None:
                result = session.report["result"]
                exposure = session.report["exposure"]

            pending = not (session.completed or session.saved)
            if pending:
                notices.append("Provisional assessment.")
                notices.append("Did you click the link / download the file?")
            for field, label in (("clicked", "Clicked link"),
                                 ("downloaded", "Downloaded file")):
                answer = exposure.get(field)
                value = "Yes" if answer is True else "No" if answer is False else "Unconfirmed"
                notices.append(f"{label}: {value}")
            if pending:
                notices.append("Did you enter a password or code?")
            category = exposure.get("submitted_category")
            disclosure = "Unconfirmed"
            if exposure.get("disclosure_answered") is True:
                if category == "password":
                    disclosure = "Password"
                elif category == "otp":
                    disclosure = "One-time code"
                elif category is None:
                    disclosure = "None reported"
            notices.append(f"Information submitted: {disclosure}")
            if (type(exposure.get("clicked")) is not bool
                    or type(exposure.get("downloaded")) is not bool
                    or exposure.get("disclosure_answered") is not True):
                notices.append("Exposure unconfirmed")
            if session.saved:
                notices.append("Report saved locally.")
            elif session.completed:
                notices.append("Report not saved. Use Retry saving.")
            else:
                notices.append("Report not saved until Finish and save or Skip unanswered.")
                notices.append("Unfinished sessions expire after 30 minutes or bot restart.")

        text = self._text_renderer.render(self._assessment_renderer.render(result))
        suffix = "\n\n" + "\n".join([*notices, self.FOOTER])
        # Telegram's UTF-16 limit counts non-BMP characters as two units.
        budget = MAX_REPLY_CHARS - len(suffix.encode("utf-16-le")) // 2
        encoded = text.encode("utf-16-le")
        if len(encoded) // 2 > budget:
            text = encoded[: (budget - 3) * 2].decode("utf-16-le", errors="ignore") + "..."
        return text + suffix
