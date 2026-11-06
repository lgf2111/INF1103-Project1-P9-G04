"""Render assessments and saved reports through a terminal."""

from .terminal import Terminal


class ReportPresenter:
    """Format assessment results, report details, and history previews."""

    def __init__(self, terminal: Terminal):
        self._terminal = terminal

    def display_result(self, result: dict | None) -> None:
        """Display a validated outcome or an explicit unavailable assessment."""
        if not result:
            self._terminal.write("\nNo assessment available.")
            return

        priority = (result.get("priority") or "unavailable").replace("_", " ").title()
        self._terminal.write("\n=== Assessment ===")
        self._terminal.write("Priority:", priority)
        self._terminal.write("Rule-based score:", result.get("score", "Unavailable"))

        if result.get("reasons"):
            self._terminal.write("\nReasons:")
            for reason in result["reasons"]:
                self._terminal.write(" -", reason)

        self._terminal.write("\nRecommended actions:")
        for number, step in enumerate(result.get("checklist", []), start=1):
            self._terminal.write(f"{number}. {step}")

    def display_record(self, record: dict) -> None:
        """Display a validated saved record, preserving absent historical fields."""
        self._terminal.write("\n=== Report details ===")
        channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
        self._terminal.write("Channel:", channels.get(record.get("channel"), "Unknown"))
        self._terminal.write("Sender:", record.get("sender") or "Unknown")
        self._terminal.write("Message:")
        self._terminal.write(record.get("message") or "No message recorded.")
        self._terminal.write("Included link:", record.get("link") or "None reported")
        self._terminal.write("Included file:", record.get("file_name") or "None reported")

        answers = {True: "Yes", False: "No", None: "Not recorded"}
        self._terminal.write("Clicked link:", answers[record.get("clicked")])
        self._terminal.write("Downloaded file:", answers[record.get("downloaded")])
        submitted = record.get("submitted_category")
        labels = {"password": "Password", "otp": "One-time code"}
        self._terminal.write(
            "Information submitted:", labels.get(submitted, submitted or "None reported")
        )

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
