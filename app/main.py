# main.py
# Ties the four managers together:
# input -> validated AI assessment -> logic -> save and display

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

    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    report = {**assessed_record, "schema_version": 1, "result": result}
    try:
        data_manager.save(report)
    except (OSError, ValueError):
        io_manager.show_message(
            "Could not save the local report; existing history preserved "
            "and database upload not attempted."
        )
    except RuntimeError as error:
        # The local write completed before the failed database request.
        io_manager.show_message("Report saved locally, but database saving failed: " + str(error))

    # io_manager.display_result expects the logic result dictionary.
    io_manager.display_result(result)

def load_reports() -> list[dict] | None:
    """Read both histories; return None when local history is unavailable and DB empty."""
    try:
        records = data_manager.fetch()
    except (RuntimeError, ValueError) as error:
        # Explain the unavailable source before reading the local copy.
        io_manager.show_message("PostgreSQL unavailable; checking reports.json: " + str(error))
        records = []

    # A failed upload can leave newer reports only in the local copy.
    try:
        local_records = data_manager.load()
    except (OSError, ValueError):
        io_manager.show_message("Could not load local report history; existing file preserved.")
        return records if records else None
    return data_manager.combine_reports(records, local_records)

def view_reports():
    """Load database or local history and send it to I/O for display."""
    records = load_reports()
    if records is not None:
        io_manager.display_list(records)

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
    finally:
        if log_handler is not None:
            logging.getLogger("ai_manager").removeHandler(log_handler)
            try:
                log_handler.close()
            except OSError:
                io_manager.show_message("Warning: could not close the diagnostic log.")

if __name__ == "__main__":
    main()
