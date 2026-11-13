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
        if result.get("matched_rule"):
            self._terminal.write("Matched rule:", result["matched_rule"])

        trace = result.get("trace") or []
        if trace:
            self._terminal.write("\nRule evaluation trace:")
            for step in trace:
                rule_name = step.get("rule_name", "Unknown rule")
                status = "matched" if step.get("matched") else "not matched"
                score = step.get("score")
                score_text = f" (score: {score})" if score is not None else ""
                self._terminal.write(f" - {rule_name}: {status}{score_text}")

        if result.get("reasons"):
            self._terminal.write("\nReasons:")
            for reason in result["reasons"]:
                self._terminal.write(" -", reason)

        self._terminal.write("\nRecommended actions:")
        for number, step in enumerate(result.get("checklist", []), start=1):
            self._terminal.write(f"{number}. {step}")

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
