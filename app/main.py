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


def load_env():
    """Load project environment values without replacing existing settings."""
    if not os.path.exists(".env"):
        return

    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

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

    # Only expected runtime/validation failures are user-facing. KeyError and
    # TypeError would be programming bugs, so let them surface instead of
    # hiding them behind a generic "check failed" message.
    except (RuntimeError, ValueError) as error:
        logging_setup.log_failure(logger, "Assessment failed")
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    report = {**assessed_record, "schema_version": 1, "result": result}
    try:
        data_manager.save(report)
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Local report save failed")
        io_manager.show_message(
            "Could not save the local report; existing history preserved "
            "and database upload not attempted."
        )
    except RuntimeError as error:
        # The local write completed before the failed database request.
        logging_setup.log_failure(logger, "Database upload failed after local save")
        io_manager.show_message("Report saved locally, but database saving failed: " + str(error))

    # io_manager.display_result expects the logic result dictionary.
    io_manager.display_result(result)

def upload_file():
    """Get a file's text via the one-shot web uploader, then assess it."""
    # Lazy import: the web server code only loads when this option is used.
    from misc import web_upload

    try:
        text = web_upload.start_and_wait_for_upload()
    except (OSError, RuntimeError) as error:
        logging_setup.log_failure(logger, "File upload failed")
        io_manager.show_message("Upload failed: " + str(error))
        return

    if not text or not text.strip():
        io_manager.show_message("No usable text in the uploaded file.")
        return

    record = io_manager.build_record_from_message(text.strip())
    check_message(record)

def load_reports() -> list[dict] | None:
    """Read both histories; return None when local history is unavailable and DB empty."""
    try:
        records = data_manager.fetch()
    except (RuntimeError, ValueError) as error:
        # Explain the unavailable source before reading the local copy.
        logging_setup.log_failure(logger, "Reading reports from PostgreSQL failed")
        io_manager.show_message("PostgreSQL unavailable; checking reports.json: " + str(error))
        records = []

    # A failed upload can leave newer reports only in the local copy.
    try:
        local_records = data_manager.load(strict=True)
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Reading local report history failed")
        io_manager.show_message("Could not load local report history; existing file preserved.")
        return records if records else None
    return data_manager.combine_reports(records, local_records)

def view_reports():
    """Load database or local history and send it to I/O for display."""
    records = load_reports()
    if records is not None:
        io_manager.display_list(records)

def main():
    load_env()
    # Set up behind-the-scenes logging to the logs/ folder before anything else,
    # so any failure (AI, database, file) is recorded. Set LOG_LEVEL=DEBUG in
    # .env to also capture full tracebacks while debugging.
    if not logging_setup.setup_logging():
        io_manager.show_message("Warning: diagnostic logging is unavailable.")
    logger.info("Application started")
    try:
        if load_reports() == []:
            io_manager.show_message("No saved reports found.")
        while True:
            choice = io_manager.main_menu()
            if choice == "1":
                check_message()
            elif choice == "2":
                view_reports()
            elif choice == "3":
                upload_file()
            elif choice == "4":
                io_manager.show_message("Bye!")
                break
            else:
                io_manager.show_message("Please choose 1, 2, 3 or 4.")
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C (interrupt) or Ctrl+D (end of input): exit cleanly, no traceback.
        io_manager.show_message("\nInterrupted. Goodbye!")
    logger.info("Application exited")

if __name__ == "__main__":
    main()
