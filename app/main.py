# main.py
# Ties the four managers together:
#   user -> io_manager -> ai_manager -> logic_manager -> data_manager

import os

import ai_manager
import data_manager
import io_manager
import logic_manager


def load_env():
    # simple .env reader so you don't have to export the key by hand.
    # looks for a .env file in the current folder: KEY=value per line.
    if not os.path.exists(".env"):
        return
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def check_new_message():
    # 1. get input from the user
    record = io_manager.collect_input()

    # 2. send it through the AI
    prompt = ai_manager.build_prompt(record)
    try:
        raw = ai_manager.call_api(prompt)
        reply = ai_manager.parse_response(raw)
        record["ai"] = ai_manager.validate_response(reply)
    except (RuntimeError, ValueError) as error:
        io_manager.show_message("Sorry, the check failed: " + str(error))
        return

    # 3. apply the rules
    result = logic_manager.evaluate(record)
    record["result"] = result

    # 4. save it and show the result
    data_manager.save(record)
    io_manager.display_record(record)


def view_saved_reports():
    records = data_manager.load()
    io_manager.display_list(records)
    for number, record in enumerate(records, start=1):
        io_manager.show_message(f"\nReport {number}")
        io_manager.display_record(record)


def main():
    load_env()
    while True:
        choice = io_manager.main_menu()
        if choice == "1":
            check_new_message()
        elif choice == "2":
            view_saved_reports()
        elif choice == "3":
            io_manager.show_message("Bye!")
            break
        else:
            io_manager.show_message("Please choose 1, 2 or 3.")


if __name__ == "__main__":
    main()
