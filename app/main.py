# main.py
# Ties the four managers together:
# input -> AI extraction -> Logic Manager -> AI response -> save and display

import logging
import os

import ai_manager
import data_manager
import io_manager
import logic_manager


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
    """Run both AI requests and the Logic Manager handoff for one user message."""
    record = io_manager.collect_input()

    try:
        # First AI request: extract details from the message.
        prompt = ai_manager.extract_prompt(record)
        raw = ai_manager.call_api(prompt)
        reply = ai_manager.parse_response(raw)
        details = ai_manager.validate_details(reply, record["message"])

        # Logic Manager validates extracted details unchanged.
        details = logic_manager.hold_details(details)

        # Second AI request: format the validated details as a response string.
        prompt = ai_manager.response_prompt(details)
        raw = ai_manager.call_api(prompt)
        reply = ai_manager.parse_response(raw)
        ai_manager.validate_reply(reply, details)

        # Only evaluate after every required AI response has passed validation.
        result = logic_manager.evaluate(record, details)

    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    # Store the input, extracted contact details, and computed assessment.
    report = {
        "channel": record["channel"],
        "sender": record["sender"],
        "message": record["message"],
        "link": record["link"],
        "file_name": record["file_name"],
        "details": details,
        "score": result["score"],
        "priority": result["priority"],
    }
    try:
        data_manager.save(report)
    except OSError:
        io_manager.show_message(
            "Could not save the local report; database upload was not attempted."
        )
    except RuntimeError as error:
        # The local write completed before the failed database request.
        io_manager.show_message("Report saved locally, but database saving failed: " + str(error))

    # io_manager.display_result expects the logic result dictionary.
    io_manager.display_result(result)

def load_reports() -> list[dict]:
    """Load PostgreSQL history, checking local JSON on failure or empty results."""
    try:
        records = data_manager.fetch()
    except RuntimeError as error:
        # Explain the unavailable source before reading the local copy.
        io_manager.show_message("PostgreSQL unavailable; checking reports.json: " + str(error))
        records = []

    # Prefer database history; consult the local copy if it returned no records.
    if records:
        return records
    return data_manager.load()

def view_reports():
    """Load database or local history and send it to I/O for display."""
    io_manager.display_list(load_reports())

def _log_write_failed(record):
    """FileHandler's procedural error callback; keep traceback output out of the CLI."""
    io_manager.show_message("Warning: could not write the diagnostic log.")

def configure_logging():
    """Connect AI diagnostics to an append-only UTF-8 file for this application run.

    Return the handler for cleanup, or None if opening fails. Logging failure is
    reported through I/O and does not prevent the menu or AI error handling.
    """
    logger = logging.getLogger("ai_manager")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        handler = logging.FileHandler("phishreport.log", encoding="utf-8")
    except OSError:
        io_manager.show_message("Warning: diagnostic logging is unavailable.")
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    # Phase 1 uses a function callback rather than a FileHandler subclass.
    handler.handleError = _log_write_failed
    logger.addHandler(handler)
    return handler


def main():
    load_env()
    log_handler = configure_logging()
    try:
        if not load_reports():
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
    finally:
        if log_handler is not None:
            logging.getLogger("ai_manager").removeHandler(log_handler)
            try:
                log_handler.close()
            except OSError:
                io_manager.show_message("Warning: could not close the diagnostic log.")

if __name__ == "__main__":
    main()
