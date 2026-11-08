# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

import os

from phishreport import logging_setup
from phishreport.ai import AIManager
from phishreport.data import DataManager
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logic import LogicManager

logger = logging_setup.get_logger(__name__)


def _friendly_ai_error(error):
    """Turn an AI RuntimeError into a short, actionable message for the user.

    Keeps the word 'failed' so the reason is clear, and adds guidance based on
    the kind of failure (offline, service error, rate limit).
    """
    text = str(error).lower()
    if "timed out" in text or "could not complete" in text:
        return (
            "The check failed: could not reach the AI service. "
            "Check your internet connection and try again."
        )
    if "http 5" in text:
        return "The check failed: the AI service is temporarily unavailable. Try again shortly."
    if "http 429" in text:
        return "The check failed: the AI service is busy (rate limited). Try again shortly."
    return "The check failed: the AI could not complete the assessment. Please try again."


def load_env() -> bool:
    """Load an optional UTF-8 file, returning False if it cannot be used safely.

    Read and validate every assignment before applying any settings. Existing
    environment values and the first occurrence of each file key take precedence.
    Failure details stay private; main reports a fixed warning after logging setup.
    """
    values = {}
    try:
        with open(".env", encoding="utf-8-sig") as stream:
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

    def __init__(self, io_manager, ai_manager, logic_manager, data_manager):
        self._io_manager = io_manager
        self._ai_manager = ai_manager
        self._logic_manager = logic_manager
        self._data_manager = data_manager

    def check_message(self, record=None):
        """Validate one combined AI response before assessment, saving or display.

        Collect input interactively when record is None; otherwise use the supplied
        record. Stop assessment on handled AI/validation failures. Save the
        version-2 outcome locally, then display it even if persistence fails.
        """
        if record is None:
            record = self._io_manager.collect_input()

        try:
            findings = self._ai_manager.assess(record)

            # Enrich a new dictionary only after every AI check passes.
            assessed_record = {**record, "ai": findings}
            result = self._logic_manager.evaluate(assessed_record)

        # RuntimeError: the AI could not complete after its retries (service down,
        # offline, rate limited). Show an actionable message; the AI is never bypassed.
        except RuntimeError as error:
            logging_setup.log_failure(logger, "Assessment failed after AI retries")
            self._io_manager.show_message(_friendly_ai_error(error))
            return
        # ValueError: bad input or an invalid AI reply - not retryable. KeyError and
        # TypeError would be programming bugs, so let them surface.
        except ValueError as error:
            logging_setup.log_failure(logger, "Assessment failed")
            self._io_manager.show_message("Sorry, the check failed: " + str(error))
            return

        # Retain the original message and assessment in the agreed version-2 format.
        report = {
            "schema_version": 2,
            "channel": record["channel"],
            "message": record["message"],
            "result": result,
        }
        try:
            self._data_manager.save(report)
        except (OSError, ValueError):
            logging_setup.log_failure(logger, "Local report save failed")
            self._io_manager.show_message(
                "Could not save the local report; existing history preserved."
            )

        # A storage failure does not discard an assessment already completed successfully.
        self._io_manager.display_result(result)

    def upload_file(self):
        """Parse uploaded email through the same I/O contract as folder imports."""
        try:
            # Load the server only when the user chooses to upload a file.
            from phishreport.cli import web_upload

            self._io_manager.show_upload_instructions(web_upload.DISPLAY_HOST, web_upload.PORT)
            upload = web_upload.start_and_wait_for_upload()
            record = self._io_manager.collect_input_from_upload(upload)
        except (OSError, RuntimeError, ValueError) as error:
            logging_setup.log_failure(logger, "File upload failed")
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
            logging_setup.log_failure(logger, "Reading local report history failed")
            self._io_manager.show_message(
                "Could not load local report history; existing file preserved."
            )
            return None

    def view_reports(self):
        """Load local JSON history and send it to I/O for display."""
        records = self.load_reports()
        if records is not None:
            self._io_manager.display_list(records)

    def run(self):
        """Initialize configuration and logging, then run the interactive menu loop.

        Check stored history on startup and delegate each choice to its manager
        flow. Handle EOF and keyboard interruption as an application exit.
        """
        env_loaded = load_env()
        # Load environment settings before logging so LOG_LEVEL is respected.
        # Set LOG_LEVEL=DEBUG to include tracebacks in subsequent failure diagnostics.
        if not logging_setup.setup_logging():
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
                    self._io_manager.show_message("Bye!")
                    break
                else:
                    self._io_manager.show_message("Please choose 1, 2, 3, 4 or 5.")
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
        data_manager=DataManager(),
    )
    app.run()


if __name__ == "__main__":
    main()
