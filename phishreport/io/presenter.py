"""Render assessments and saved reports through a terminal."""

from dataclasses import asdict

from phishreport.model import AssessmentResult, Report

from .terminal import Terminal


class ReportPresenter:
    """Format assessment results, report details, and history previews."""

    def __init__(self, terminal: Terminal):
        self._terminal = terminal

    def display_result(self, result: AssessmentResult | dict | None) -> None:
        """Display an outcome through its tolerant, immutable assessment view."""
        if isinstance(result, dict):
            result = Report({"result": result}).result
        if result is None:
            self._terminal.write("\nNo assessment available.")
            return

        priority = (result.priority or "unavailable").replace("_", " ").title()
        self._terminal.write("\n=== Assessment ===")
        self._terminal.write("Priority:", priority)
        score = result.score if result.score is not None else "Unavailable"
        self._terminal.write("Rule-based score:", score)
        if result.matched_rule:
            self._terminal.write("Matched rule:", result.matched_rule)

        if result.trace:
            self._terminal.write("\nRule evaluation trace:")
            for step in result.trace:
                status = "matched" if step.matched else "not matched"
                score_text = f" (score: {step.score})" if step.score is not None else ""
                self._terminal.write(f" - {step.rule_name}: {status}{score_text}")

        if result.reasons:
            self._terminal.write("\nReasons:")
            for reason in result.reasons:
                self._terminal.write(" -", reason)

        self._terminal.write("\nRecommended actions:")
        for number, step in enumerate(result.checklist, start=1):
            self._terminal.write(f"{number}. {step}")

    def display_record(self, record: dict) -> None:
        """Display a saved report's tolerant view without inventing absent history."""
        report = Report(record)
        is_exposure_report = report.has_nested_exposure
        self._terminal.write("\n=== Report details ===")
        channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
        self._terminal.write("Channel:", channels.get(report.channel, "Unknown"))
        self._terminal.write("Sender:", report.sender or "Unknown")
        self._terminal.write("Message:")
        self._terminal.write(report.message or "No message recorded.")
        self._terminal.write("Included link:", report.link or "None reported")
        file_label = report.file_name or "None reported"
        if is_exposure_report and report.has_file and report.file_name is None:
            file_label = "Mentioned (filename unknown)"
        self._terminal.write("Included file:", file_label)

        exposure = report.exposure
        clicked = exposure.clicked if exposure is not None else None
        downloaded = exposure.downloaded if exposure is not None else None
        submitted = exposure.submitted_category if exposure is not None else None
        disclosure_answered = exposure.disclosure_answered if exposure is not None else None
        answers = {
            True: "Yes", False: "No",
            None: "Unconfirmed" if is_exposure_report else "Not recorded",
        }
        self._terminal.write("Clicked link:", answers[clicked])
        self._terminal.write("Downloaded file:", answers[downloaded])
        labels = {"password": "Password", "otp": "One-time code"}
        disclosure_label = labels.get(submitted, submitted or "None reported")
        if is_exposure_report and not disclosure_answered:
            disclosure_label = "Unconfirmed"
        self._terminal.write("Information submitted:", disclosure_label)
        if is_exposure_report and (
            clicked is None or downloaded is None or not disclosure_answered
        ):
            self._terminal.write("Exposure unconfirmed")

        result = asdict(report.result) if report.result is not None else None
        if result is not None and report.result.score is None:
            result.pop("score")
        self.display_result(result)

    def display_list(self, records: list[dict]) -> None:
        """Display tolerant report views with a shortened preview of each message."""
        if not records:
            self._terminal.write("No saved reports yet.")
            return

        self._terminal.write("\n=== Saved reports ===")
        for number, record in enumerate(records, start=1):
            report = Report(record)
            result = report.result
            priority = result.priority if result is not None else None
            priority = (priority or "unavailable").replace("_", " ").title()
            channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
            channel = channels.get(report.channel, "Unknown")
            score = result.score if result is not None else None
            if score is None:
                score = "Unavailable"
            preview = " ".join((report.message or "").split())
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
