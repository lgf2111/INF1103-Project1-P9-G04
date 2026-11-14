"""Render assessments and saved reports through a terminal."""

from .plain_text_renderer import PlainTextRenderer
from .render import AssessmentRenderer
from .terminal import Terminal


class ReportPresenter:
    """Format assessment results, report details, and history previews."""

    def __init__(self, terminal: Terminal):
        self._terminal = terminal
        self._assessment_renderer = AssessmentRenderer()
        self._text_renderer = PlainTextRenderer()

    def display_result(self, result: dict | None) -> None:
        """Display a validated outcome or an explicit unavailable assessment."""
        document = self._assessment_renderer.render(result)
        rendered = self._text_renderer.render(document)
        for section_number, section in enumerate(rendered.split("\n\n")):
            for line_number, line in enumerate(section.split("\n")):
                prefix = "\n" if line_number == 0 else ""
                self._terminal.write(prefix + line)

    def display_record(self, record: dict) -> None:
        """Display a validated saved record, preserving absent historical fields."""
        is_exposure_report = record.get("schema_version") == 3
        self._terminal.write("\n=== Report details ===")
        channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
        self._terminal.write("Channel:", channels.get(record.get("channel"), "Unknown"))
        self._terminal.write("Sender:", record.get("sender") or "Unknown")
        self._terminal.write("Message:")
        self._terminal.write(record.get("message") or "No message recorded.")
        self._terminal.write("Included link:", record.get("link") or "None reported")
        file_label = record.get("file_name") or "None reported"
        if is_exposure_report and record["has_file"] and record["file_name"] is None:
            file_label = "Mentioned (filename unknown)"
        self._terminal.write("Included file:", file_label)

        exposure = record["exposure"] if is_exposure_report else record
        answers = {
            True: "Yes", False: "No",
            None: "Unconfirmed" if is_exposure_report else "Not recorded",
        }
        self._terminal.write("Clicked link:", answers[exposure.get("clicked")])
        self._terminal.write("Downloaded file:", answers[exposure.get("downloaded")])
        submitted = exposure.get("submitted_category")
        labels = {"password": "Password", "otp": "One-time code"}
        disclosure_label = labels.get(submitted, submitted or "None reported")
        if is_exposure_report and not exposure["disclosure_answered"]:
            disclosure_label = "Unconfirmed"
        self._terminal.write("Information submitted:", disclosure_label)
        if is_exposure_report and (
            exposure["clicked"] is None
            or exposure["downloaded"] is None
            or not exposure["disclosure_answered"]
        ):
            self._terminal.write("Exposure unconfirmed")

        self.display_result(record.get("result") or {})

    def display_list(self, records: list[dict]) -> None:
        """Display saved summaries with a shortened preview of each message."""
        if not records:
            self._terminal.write("No saved reports yet.")
            return

        self._terminal.write("\n=== Saved reports ===")
        for number, record in enumerate(records, start=1):
            result = record.get("result") or record
            priority = (result.get("priority") or "unavailable").replace("_", " ").title()
            channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
            channel = channels.get(record.get("channel"), "Unknown")
            score = result.get("score")
            if score is None:
                score = "Unavailable"
            preview = " ".join((record.get("message") or "").split())
            if len(preview) > 50:
                preview = preview[:47] + "..."
            self._terminal.write(f"{number}. {channel} | {priority} | Score: {score}")
            self._terminal.write(f"   {preview}")

    def display_summary(self, summary, description: str = "all reports") -> None:
        """Display counts and statistics for the reports that matched a filter."""
        self._terminal.write("\n=== Report summary ===")
        self._terminal.write("Showing:", description)
        self._terminal.write("Reports:", summary.total)
        if summary.total == 0:
            self._terminal.write("No saved reports match.")
            return
        for section in summary.sections:
            self._terminal.write(f"\n{section.title}:")
            for label, value in section.rows:
                self._terminal.write(f" - {label}: {value}")
