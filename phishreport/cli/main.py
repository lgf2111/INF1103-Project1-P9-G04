# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

import os
from uuid import uuid4

from phishreport.ai import AIManager
from phishreport.ai.errors import AIErrorTranslator
from phishreport.assessment import AssessmentService
from phishreport.data import DataManager
from phishreport.data.factory import create_report_storage
from phishreport.data.repair import repair_history
from phishreport.errors import AssessmentError
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.io import IOManager
from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.commands import CommandRequest, CommandRouter
from phishreport.io.report_csv import ReportExportError, export_reports_csv
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager
from phishreport.reporting import ReportQueryResult, ReportQueryService

logger = AppLogging.get_logger(__name__)


class EnvLoader:
    """Load an optional UTF-8 settings file into the process environment."""

    def __init__(self, path: str = ".env"):
        self._path = path

    def load(self) -> bool:
        """Return False if the file cannot be used safely.

        Read and validate every assignment before applying any settings. Existing
        environment values and the first occurrence of each file key take precedence.
        Failure details stay private; the app reports a fixed warning after logging setup.
        """
        values = {}
        try:
            with open(self._path, encoding="utf-8-sig") as stream:
                for line in stream:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = (part.strip() for part in line.split("=", 1))
                        if not key or "\x00" in key or "\x00" in value:
                            return False
                        values.setdefault(key, value)
        except FileNotFoundError:
            return True  # The file is optional when settings come from the environment.
        except (OSError, UnicodeError):
            return False

        for key, value in values.items():
            os.environ.setdefault(key, value)
        return True


class PhishReportApp:
    """Run the CLI workflows with the supplied managers."""

    def __init__(
        self,
        io_manager,
        ai_manager,
        logic_manager,
        data_manager,
        env_loader=None,
        error_translator=None,
        feedback_service=None,
    ):
        self._io_manager = io_manager
        self._ai_manager = ai_manager
        self._logic_manager = logic_manager
        self._data_manager = data_manager
        self._report_query = ReportQueryService(data_manager, logic_manager)
        self._env_loader = env_loader or EnvLoader()
        self._error_translator = error_translator or AIErrorTranslator()
        self._feedback_service = feedback_service

    @property
    def _assessment(self):
        """Build the shared assessment workflow from the app's current managers."""
        return AssessmentService(self._ai_manager, self._logic_manager)

    def check_message(self, record=None, *, command_text: str | None = None):
        """Validate one combined AI response before assessment, saving or display.

        Collect input interactively when record is None; otherwise use the supplied
        record. Explicit command_text is full raw slash input (e.g. /check text)
        routed through the shared command catalog.
        Stop assessment on handled AI/validation failures. Save the
        version-3 outcome locally, then display it even if persistence fails.
        Offer the optional exposure checklist only after a successful save and
        replace the same report when the user confirms an answer.
        """
        if command_text is None and record is None:
            try:
                record = self._io_manager.collect_input()
            except AssessmentError as error:
                AppLogging.log_failure(logger, "Input collection failed")
                self._io_manager.show_message(self._error_translator.translate(error))
                return
            except (OSError, ValueError):
                AppLogging.log_failure(logger, "Input collection failed")
                self._io_manager.show_message("Sorry, the check failed. Please try again.")
                return

        if command_text is not None:
            catalog = discover_commands(CommandCapabilities(
                prepare_record=lambda request: self._io_manager.build_record_from_message(
                    request.text
                ),
                assess_record=self._assessment.assess_with_findings,
                session_status=lambda request: "CLI conversation active",
                report_count=lambda: len(self._report_query.load()),
            ))
            router = CommandRouter(catalog)
            resolved = router.resolve(command_text)
            request = CommandRequest(command_text, "cli")

        try:
            if command_text is None:
                snapshot = self._assessment.assess_with_findings(record)
                result, findings = snapshot.result, snapshot.findings
            else:
                try:
                    reply = router.route(request)
                except (AssessmentError, OSError, ValueError, RuntimeError) as error:
                    if resolved.policy.failure == "assessment":
                        if not isinstance(error, OSError):
                            raise
                        AppLogging.log_failure(logger, "Assessment failed")
                        self._io_manager.show_message("Sorry, the check failed. Please try again.")
                    elif resolved.policy.failure == "history":
                        AppLogging.log_failure(logger, "Reading local report history failed")
                        self._io_manager.show_message(
                            "Could not load local report history; existing file preserved."
                        )
                    else:
                        AppLogging.log_failure(logger, "Command failed")
                        self._io_manager.show_message(
                            "Sorry, the command failed. Please try again."
                        )
                    return
                if reply is None:
                    self._io_manager.show_message(
                        "Please choose 1, 2, 3, 4, 5, upload or feedback."
                    )
                    return
                if resolved.policy.execution != "assessment" or reply.kind != "assessment":
                    self._io_manager.show_message(reply.text)
                    return
                outcome = request.session["check_outcome"]
                record, result, findings = outcome.record, outcome.result, outcome.findings

        except AssessmentError as error:
            AppLogging.log_failure(logger, "Assessment failed")
            self._io_manager.show_message(self._error_translator.translate(error))
            return
        # Retain the original message and assessment with an identifier for feedback.
        assessment_id = str(uuid4())
        result = {**result, "assessment_id": assessment_id}
        report = self._build_report(record, result)
        saved = True
        try:
            self._data_manager.save(report)
        except AssessmentError as error:
            saved = False
            AppLogging.log_failure(logger, "Local report save failed")
            self._io_manager.show_message(self._error_translator.translate(error))
        except (OSError, ValueError):
            saved = False
            AppLogging.log_failure(logger, "Local report save failed")
            self._io_manager.show_message(
                "Could not save the local report; existing history preserved."
            )

        # A storage failure does not discard an assessment already completed successfully.
        self._io_manager.display_result(result)

        if saved and findings is not None and self._supports_exposure_follow_up():
            self._collect_exposure_update(record, findings, assessment_id)

    def _supports_exposure_follow_up(self) -> bool:
        """Whether this transport offers the optional post-verdict checklist."""
        return getattr(
            self._io_manager, "supports_post_verdict_exposure", False,
        ) is True

    def _collect_exposure_update(self, record: dict, findings: dict, assessment_id: str):
        """Offer the checklist and replace the saved report with a re-score.

        The retained findings keep the AI out of this path. Skipping, Escape or
        empty confirmation leaves the already saved plain assessment untouched.
        """
        try:
            exposure = self._io_manager.collect_exposure()
        except (EOFError, OSError):
            return
        if exposure is None:
            return

        updated_record = {**record, **exposure}
        try:
            updated = self._assessment.rescore(updated_record, findings)
            report = self._assessment.build_exposure_report(
                updated_record, updated, exposure, assessment_id=assessment_id,
            )
            self._data_manager.save(report)
        except AssessmentError as error:
            AppLogging.log_failure(logger, "Local report update failed")
            self._io_manager.show_message(self._error_translator.translate(error))
            return
        except (OSError, ValueError):
            AppLogging.log_failure(logger, "Local report update failed")
            self._io_manager.show_message(
                "Could not update the local report; existing history preserved."
            )
            return

        self._io_manager.display_result({**updated, "assessment_id": assessment_id})
        self._io_manager.show_message("Saved report updated.")

    def _build_report(self, record: dict, result: dict) -> dict:
        """Save answered exposure; otherwise use the plain v3 record."""
        exposure_fields = ("clicked", "downloaded", "submitted_category")
        if record.get("disclosure_answered") is not True or any(
            field not in record for field in exposure_fields
        ):
            return self._assessment.build_report(record, result)

        exposure = {field: record[field] for field in exposure_fields}
        exposure["disclosure_answered"] = True
        saved_result = {
            key: value for key, value in result.items() if key != "assessment_id"
        }
        return self._assessment.build_exposure_report(
            record, saved_result, exposure, assessment_id=result.get("assessment_id"),
        )

    def correct_latest_report(self):
        """Apply a menu correction to the most recent saved assessment."""
        if self._feedback_service is None:
            self._io_manager.show_message("Feedback is unavailable.")
            return
        records = self.load_reports()
        if records is None:
            return
        if not records:
            self._io_manager.show_message("No saved reports yet.")
            return
        report = records[-1]
        assessment_id = report.get("assessment_id")
        result = report.get("result")
        if not isinstance(assessment_id, str) or not isinstance(result, dict):
            self._io_manager.show_message(
                "The most recent report cannot take feedback."
            )
            return
        assessment_result = {**result, "assessment_id": assessment_id}
        try:
            correction = self._io_manager.collect_correction()
            self._feedback_service.submit(
                assessment_id=assessment_id,
                assessment_result=assessment_result,
                **correction,
            )
        except (AssessmentError, OSError, ValueError):
            AppLogging.log_failure(logger, "Saving assessment feedback failed")
            self._io_manager.show_message(
                "Could not save your feedback. The assessment result is unchanged."
            )
            return
        self._io_manager.show_message("Thank you. Your feedback was saved for review.")

    def upload_file(self):
        """Parse uploaded email through the same I/O contract as folder imports."""
        try:
            # Load the server only when the user chooses to upload a file.
            from phishreport.cli import web_upload

            self._io_manager.show_upload_instructions(web_upload.DISPLAY_HOST, web_upload.PORT)
            upload = web_upload.BrowserUploadService().receive_upload()
            record = self._io_manager.collect_input_from_upload(upload)
        except AssessmentError as error:
            AppLogging.log_failure(logger, "File upload failed")
            self._io_manager.show_message(error.user_message)
            return
        except (OSError, ValueError):
            AppLogging.log_failure(logger, "File upload failed")
            self._io_manager.show_message("Upload failed. Please try again with an .eml email.")
            return

        self.check_message(record)

    def load_reports(self) -> list[dict] | None:
        """Return validated history, or None after reporting a read failure.

        An empty list means missing/empty history; None means history could not
        be read safely. Keep this distinction when deciding what to display.
        """
        try:
            return self._report_query.load()
        except (AssessmentError, OSError, ValueError):
            AppLogging.log_failure(logger, "Reading local report history failed")
            self._io_manager.show_message(
                "Could not load local report history; existing file preserved."
            )
            return None

    def view_reports(self):
        """Load local history and send it to I/O for display."""
        records = self.load_reports()
        if records is not None:
            self._io_manager.display_list(records)

    def _query_reports(self) -> ReportQueryResult | None:
        """Load history, prompt for filters and handle user-facing failures."""
        records = self.load_reports()
        if records is None:
            return None
        if not records:
            self._io_manager.show_message("No saved reports yet.")
            return None
        try:
            return self._report_query.query(
                records=records, **self._io_manager.collect_summary_filter()
            )
        except AssessmentError as error:
            AppLogging.log_failure(logger, "Report filter validation failed")
            self._io_manager.show_message(error.user_message)
        except ValueError:
            AppLogging.log_failure(logger, "Report filter validation failed")
            self._io_manager.show_message(
                "Invalid report filter. Check the channel, priority and minimum score, "
                "then try again."
            )
        return None

    def summarize_reports(self):
        """Show counts and statistics for matching saved reports."""
        selection = self._query_reports()
        if selection is not None:
            summary = self._report_query.summarize(selection)
            self._io_manager.display_summary(summary, selection.description)

    def export_reports(self):
        """Preview matching reports and optionally export the same selection."""
        selection = self._query_reports()
        if selection is None:
            return
        if not selection.records:
            self._io_manager.show_message("No saved reports match.")
            return

        self._io_manager.display_list(selection.records)
        destination = self._io_manager.collect_csv_path()
        if destination is None:
            return

        try:
            export_reports_csv(destination, selection.records)
        except ReportExportError:
            AppLogging.log_failure(logger, "Writing report CSV failed")
            self._io_manager.show_message(
                "Could not export reports. Choose a new file in a writable folder."
            )
            return
        self._io_manager.show_message(f"Exported {len(selection.records)} report(s) to CSV.")

    def run(self):
        """Initialize configuration and logging, then run the interactive menu loop.

        Check stored history on startup and delegate each choice to its manager
        flow. Handle EOF and keyboard interruption as an application exit.
        """
        env_loaded = self._env_loader.load()
        # Load environment settings before logging so LOG_LEVEL is respected.
        # Set LOG_LEVEL=DEBUG to include tracebacks in subsequent failure diagnostics.
        if not AppLogging.setup():
            self._io_manager.show_message("Warning: diagnostic logging is unavailable.")
        if not env_loaded:
            # No raw file/exception details: even DEBUG must not expose credentials.
            logger.warning("Optional .env could not be loaded; existing environment retained.")
            self._io_manager.show_message(
                "Warning: .env could not be loaded. Using existing environment settings."
            )
        logger.info("Application started")
        try:
            if self.load_reports() == []:
                self._io_manager.show_message("No saved reports found.")
            while True:
                choice = self._io_manager.main_menu()
                normalized = choice.strip().lower()
                if choice.lstrip().startswith("/"):
                    self.check_message(command_text=choice)
                elif normalized == "1":
                    # Paste one message; its inputs are derived from the text.
                    self.check_message()
                elif normalized == "2":
                    # View previous assessments.
                    self.view_reports()
                elif normalized == "3":
                    # Counts and statistics for saved reports, optionally filtered.
                    self.summarize_reports()
                elif normalized == "4":
                    self.export_reports()
                elif normalized == "5":
                    self._io_manager.show_message("Bye!")
                    break
                elif normalized == "upload":
                    # Browser-based file upload stays available by keyword.
                    self.upload_file()
                elif normalized == "feedback":
                    # Correct the most recent saved assessment.
                    self.correct_latest_report()
                else:
                    self._io_manager.show_message(
                        "Please choose 1, 2, 3, 4, 5, upload or feedback."
                    )
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C (interrupt) or Ctrl+D (end of input): exit cleanly, no traceback.
            self._io_manager.show_message("\nInterrupted. Goodbye!")
        logger.info("Application exited")


def main():
    """Compose and run the CLI with its production managers."""
    data_manager = DataManager(create_report_storage())
    repair_history(data_manager)
    app = PhishReportApp(
        io_manager=IOManager(ConsoleTerminal()),
        ai_manager=AIManager(),
        logic_manager=LogicManager(),
        data_manager=data_manager,
        feedback_service=FeedbackService(
            FeedbackStore(os.environ.get("PHISHREPORT_FEEDBACK_PATH", "feedback.json"))
        ),
    )
    app.run()


if __name__ == "__main__":
    main()
