# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

import os

import ai_manager
import data_manager
import io_manager
import logging_setup
import logic_manager

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

def check_message():
    """Validate one combined AI response before assessment, saving or display."""
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
    if load_reports() == []:
        io_manager.show_message("No saved reports found.")
    while True:
        choice = io_manager.main_menu()
        if choice == "1":
            check_message()
        elif choice == "2":
            view_reports()
        elif choice == "3":
            io_manager.show_message("Bye!")
            break
        else:
            io_manager.show_message("Please choose 1, 2 or 3.")
    logger.info("Application exited")

if __name__ == "__main__":
    main()
