# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

import os

import ai_manager
import data_manager
import io_manager
import logic_manager
from misc import logging_setup

# web_upload is imported lazily inside upload_file() so the web server code only
# loads when the user actually chooses to upload a file.

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


def check_message(record=None):
    """Validate one combined AI response before assessment, saving or display.

    If no record is given, collect one interactively. A caller (e.g. the file
    upload option) may pass a pre-built record instead.
    """
    if record is None:
        record = io_manager.collect_input()

    try:
        prompt = ai_manager.build_prompt(record)
        raw = ai_manager.call_api(prompt)
        reply = ai_manager.parse_response(raw)
        findings = ai_manager.validate_response(reply)
        ai_manager.validate_details(findings["details"], record["message"])

        # Enrich a new dictionary only after every AI check passes.
        assessed_record = {**record, "ai": findings}
        result = logic_manager.evaluate(assessed_record)

    # RuntimeError: the AI could not complete after its retries (service down,
    # offline, rate limited). Show an actionable message; the AI is never bypassed.
    except RuntimeError as error:
        logging_setup.log_failure(logger, "Assessment failed after AI retries")
        io_manager.show_message(_friendly_ai_error(error))
        return
    # ValueError: bad input or an invalid AI reply - not retryable. KeyError and
    # TypeError would be programming bugs, so let them surface.
    except ValueError as error:
        logging_setup.log_failure(logger, "Assessment failed")
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    # Retain the original message and assessment in the agreed version-2 format.
    report = {
        "schema_version": 2,
        "channel": record["channel"],
        "message": record["message"],
        "result": result,
    }
    try:
        data_manager.save(report)
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Local report save failed")
        io_manager.show_message("Could not save the local report; existing history preserved.")

    # io_manager.display_result expects the logic result dictionary.
    io_manager.display_result(result)


def upload_file():
    """Parse uploaded email through the same I/O contract as folder imports."""
    try:
        from misc import web_upload

        io_manager.show_upload_instructions(web_upload.DISPLAY_HOST, web_upload.PORT)
        upload = web_upload.start_and_wait_for_upload()
        record = io_manager.collect_input_from_upload(upload)
    except (OSError, RuntimeError, ValueError) as error:
        logging_setup.log_failure(logger, "File upload failed")
        io_manager.show_message("Upload failed: " + str(error))
        return

    check_message(record)


def load_reports() -> list[dict] | None:
    """Read JSON history; distinguish an unavailable file from empty history."""
    try:
        return data_manager.load(strict=True)
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Reading local report history failed")
        io_manager.show_message("Could not load local report history; existing file preserved.")
        return None


def view_reports():
    """Load local JSON history and send it to I/O for display."""
    records = load_reports()
    if records is not None:
        io_manager.display_list(records)


def main():
    env_loaded = load_env()
    # Set up behind-the-scenes logging to the logs/ folder before anything else,
    # so any failure (AI or file) is recorded. Set LOG_LEVEL=DEBUG in
    # .env to also capture full tracebacks while debugging.
    if not logging_setup.setup_logging():
        io_manager.show_message("Warning: diagnostic logging is unavailable.")
    if not env_loaded:
        # No raw file/exception details: even DEBUG must not expose credentials.
        logger.warning("Optional .env could not be loaded; existing environment retained.")
        io_manager.show_message(
            "Warning: .env could not be loaded. Using existing environment settings."
        )
    logger.info("Application started")
    try:
        if load_reports() == []:
            io_manager.show_message("No saved reports found.")
        while True:
            choice = io_manager.main_menu()
            if choice == "1":
                # Manual Email, SMS or Chat input.
                check_message()
            elif choice == "2":
                # Import a .eml file chosen from the user's saved email folder.
                record = io_manager.collect_input_from_folder()
                if record is not None:
                    check_message(record)
            elif choice == "3":
                # Existing browser-based file upload.
                upload_file()
            elif choice == "4":
                # View previous assessments.
                view_reports()
            elif choice == "5":
                io_manager.show_message("Bye!")
                break
            else:
                io_manager.show_message("Please choose 1, 2, 3, 4 or 5.")
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C (interrupt) or Ctrl+D (end of input): exit cleanly, no traceback.
        io_manager.show_message("\nInterrupted. Goodbye!")
    logger.info("Application exited")


if __name__ == "__main__":
    main()
