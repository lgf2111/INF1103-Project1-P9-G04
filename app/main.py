# main.py
# Ties the four managers together:
# input -> AI extraction -> Logic Manager -> AI response -> save and display

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

        # Logic Manager computes the logic-layer result for display.
        result = logic_manager.evaluate(record, details)

        # Second AI request: format the validated details as a response string.
        prompt = ai_manager.response_prompt(details)
        raw = ai_manager.call_api(prompt)
        reply = ai_manager.parse_response(raw)
        ai_manager.validate_reply(reply, details)

    except (RuntimeError, ValueError, KeyError, TypeError) as error:
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    # Store only the agreed input fields and extracted contact details.
    report = {
        "channel": record["channel"],
        "sender": record["sender"],
        "message": record["message"],
        "link": record["link"],
        "file_name": record["file_name"],
        "details": details,
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

def main():
    """Load settings and run the application's menu until the user quits."""
    load_env()
    # Load history before accepting menu input and explain an empty result.
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

if __name__ == "__main__":
    main()
