# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

import os

from phishreport.ai import AIManager
from phishreport.ai.errors import AIErrorTranslator
from phishreport.assessment import AssessmentService
from phishreport.data import DataManager
from phishreport.data.factory import create_report_storage
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.io import IOManager
from phishreport.io.check_command import CheckCommand
from phishreport.io.commands import CommandRequest
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager

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
        record. Explicit command_text uses the shared pasted-message command.
        Stop assessment on handled AI/validation failures. Save the
        version-3 outcome locally, then display it even if persistence fails.
        """
        if command_text is None and record is None:
            record = self._io_manager.collect_input()

        try:
            if command_text is None:
                result = self._assessment.assess(record)
            else:
                command = CheckCommand(
                    prepare_record=lambda request: self._io_manager.build_record_from_message(
                        request.text, channel="chat"
                    ),
                    assess_record=self._assessment.assess,
                )
                request = CommandRequest(command_text, "cli")
                reply = command.execute(request)
                if reply.kind == "usage":
                    self._io_manager.show_message(reply.text)
                    return
                outcome = request.session["check_outcome"]
                record, result = outcome.record, outcome.result

        # RuntimeError: the AI could not complete after its retries (service down,
        # offline, rate limited). Show an actionable message; the AI is never bypassed.
        except RuntimeError as error:
            AppLogging.log_failure(logger, "Assessment failed after AI retries")
            self._io_manager.show_message(self._error_translator.translate(error))
            return
        # ValueError: bad input or an invalid AI reply - not retryable. KeyError and
        # TypeError would be programming bugs, so let them surface.
        except ValueError as error:
            AppLogging.log_failure(logger, "Assessment failed")
            self._io_manager.show_message("Sorry, the check failed: " + str(error))
            return

        # Retain the original message and assessment with an identifier for feedback.
        report = self._assessment.build_report(record, result)
        report_saved = False
        try:
            self._data_manager.save(report)
            report_saved = True
        except (OSError, ValueError):
            AppLogging.log_failure(logger, "Local report save failed")
            self._io_manager.show_message(
                "Could not save the local report; existing history preserved."
            )

        # A storage failure does not discard an assessment already completed successfully.
        self._io_manager.display_result(result)
        if report_saved and self._feedback_service is not None:
            self._collect_feedback(result)

    def _collect_feedback(self, result: dict) -> None:
        """Store optional user feedback without changing the completed assessment."""
        feedback = self._io_manager.collect_feedback()
        if feedback is None:
            return
        try:
            self._feedback_service.submit(
                assessment_id=result["assessment_id"],
                assessment_result=result,
                **feedback,
            )
        except (OSError, ValueError):
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
        except (OSError, RuntimeError, ValueError) as error:
            AppLogging.log_failure(logger, "File upload failed")
            self._io_manager.show_message("Upload failed: " + str(error))
            return

        self.check_message(record)

    def load_reports(self) -> list[dict] | None:
        """Return validated JSON history, or None after reporting a read failure.

        An empty list means missing/empty history; None means history could not
        be read safely. Keep this distinction when deciding what to display.
        """
        try:
            return self._data_manager.load(strict=True)
        except (OSError, ValueError):
            AppLogging.log_failure(logger, "Reading local report history failed")
            self._io_manager.show_message(
                "Could not load local report history; existing file preserved."
            )
            return None

    def view_reports(self):
        """Load local JSON history and send it to I/O for display."""
        records = self.load_reports()
        if records is not None:
            self._io_manager.display_list(records)

    def summarize_reports(self):
        """Ask for filter criteria, then show counts and statistics for matching reports."""
        records = self.load_reports()
        if records is None:
            return
        try:
            report_filter = self._logic_manager.build_filter(
                **self._io_manager.collect_summary_filter()
            )
        except ValueError as error:
            self._io_manager.show_message(str(error))
            return
        matching = self._data_manager.query(report_filter.matches)
        summary = self._logic_manager.summarize(matching)
        self._io_manager.display_summary(summary, report_filter.describe())

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
                if choice == "1":
                    # Manual Email, SMS or Chat input.
                    self.check_message()
                elif choice == "2":
                    # Import a .eml file chosen from the user's saved email folder.
                    record = self._io_manager.collect_input_from_folder()
                    if record is not None:
                        self.check_message(record)
                elif choice == "3":
                    # Existing browser-based file upload.
                    self.upload_file()
                elif choice == "4":
                    # View previous assessments.
                    self.view_reports()
                elif choice == "5":
                    # Counts and statistics for saved reports, optionally filtered.
                    self.summarize_reports()
                elif choice == "6":
                    self._io_manager.show_message("Bye!")
                    break
                else:
                    self._io_manager.show_message("Please choose 1, 2, 3, 4, 5 or 6.")
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C (interrupt) or Ctrl+D (end of input): exit cleanly, no traceback.
            self._io_manager.show_message("\nInterrupted. Goodbye!")
        logger.info("Application exited")


def main():
    """Compose and run the CLI with its production managers."""
    app = PhishReportApp(
        io_manager=IOManager(ConsoleTerminal()),
        ai_manager=AIManager(),
        logic_manager=LogicManager(),
        data_manager=DataManager(create_report_storage()),
        feedback_service=FeedbackService(
            FeedbackStore(os.environ.get("PHISHREPORT_FEEDBACK_PATH", "feedback.json"))
        ),
    )
    app.run()


if __name__ == "__main__":
    main()
