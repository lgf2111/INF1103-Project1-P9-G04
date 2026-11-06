# io_manager.py
# All input() and print() live here. OWNER: Jeremy Goh & Bryan Lee.

from pathlib import Path

import local_settings
from io_core import EmlReader, eml

MAX_EML_BYTES = eml.MAX_EML_BYTES
MAX_MIME_PARTS = eml.MAX_MIME_PARTS
MAX_MIME_DEPTH = eml.MAX_MIME_DEPTH
MAX_MESSAGE_CHARS = eml.MAX_MESSAGE_CHARS
UPLOAD_TYPE_MESSAGE = (
    "Only .eml email files are supported. Images and attachments are not analysed."
)


_eml_reader = EmlReader()


def main_menu():
    """Display the CLI menu and return a validated, normalized menu choice."""
    print("\n=== PhishReport ===")
    print("1. Check a new message (Manual Input)")
    print("2. Import an email (.eml file)")
    print("3. Upload an email (.eml file)")
    print("4. View saved reports")
    print("5. Quit")

    return get_valid_choice(
        "Choose 1-5: ",
        ("1", "2", "3", "4", "5"),
        "Invalid choice. Please choose 1-5: ",
    )


def get_valid_choice(prompt, valid_choices, error_message):
    """Prompt until stripped, lowercase input matches one of valid_choices.

    Print error_message after an invalid answer. EOF and keyboard interruption
    propagate to the main loop for a consistent application exit.
    """
    choice = input(prompt).strip().lower()

    while choice not in valid_choices:
        choice = input(error_message).strip().lower()

    return choice


def collect_input() -> dict:
    """Collect validated manual fields, then use the shared exposure questions."""
    channel = get_channel()
    sender = get_sender()
    message = get_message()
    return build_record_from_message(message, channel=channel, sender=sender)


def build_record_from_message(
    message: str, channel: str = "email", sender: str | None = None
) -> dict:
    """Build a record from already-obtained message text (e.g. an uploaded file).

    Manual, folder and upload collection all use this single action/record contract.
    The caller supplies message text validated by its collection or decoding path.
    """
    has_link, link = get_link_information()
    has_file, file_name = get_file_information()
    user_actions = collect_user_actions(has_link, has_file)
    return {
        "channel": channel,
        "sender": sender,
        "message": message,
        "has_link": has_link,
        "link": link,
        "has_file": has_file,
        "file_name": file_name,
        "clicked": user_actions["clicked"],
        "downloaded": user_actions["downloaded"],
        "submitted_category": user_actions["submitted_category"],
    }


def collect_input_from_upload(upload):
    """Use the folder import's MIME parser and exposure contract for browser EML."""
    if not upload["filename"].lower().endswith(".eml"):
        raise ValueError(UPLOAD_TYPE_MESSAGE)
    sender, message = read_eml_bytes(upload["content"])
    return build_record_from_message(message, sender=sender)


def show_upload_instructions(host, port):
    """Print the browser upload address and waiting instructions; do not start a server."""
    print(f"\nOpen http://{host}:{port} in your browser to upload an .eml email.")
    print("Waiting for upload... (Ctrl+C to cancel)")


def collect_input_from_folder() -> dict | None:
    """Load a selected email and reuse the same record builder as other routes."""
    loaded = get_eml_from_folder()
    if loaded is None:
        return None
    sender, message = loaded
    return build_record_from_message(message, sender=sender)


def ask_yes_no(question):
    """Prompt until yes/y or no/n is entered, ignoring case and surrounding spaces.

    Return a boolean; leave cancellation handling to the application loop.
    """
    answer = input(question).strip().lower()

    while answer not in ("y", "yes", "n", "no"):
        answer = input("Please type yes/y or no/n: ").strip().lower()

    return answer in ("y", "yes")


def get_channel():
    """Return the user-selected channel: email, sms or chat."""
    return get_valid_choice(
        "Enter channel (Email/SMS/Chat): ",
        ("email", "sms", "chat"),
        "Invalid channel. Please enter Email, SMS, or Chat: ",
    )


def get_sender():
    """Return stripped sender text, or None for a blank answer; do not verify identity."""
    sender = input("Enter sender information (press Enter if unknown): ").strip()

    if sender == "":
        return None

    return sender


def get_message():
    """Prompt for a single nonblank line and return its stripped message text."""
    message = input("Enter the suspicious message: ").strip()

    while message == "":
        message = input("Message cannot be blank. Please enter the suspicious message: ").strip()

    return message


def validate_mime_limits(email_message):
    """Check MIME part count, depth and rejected structural defects."""
    return eml.validate_mime_limits(email_message)


def read_eml_details(file_path):
    """Read a bounded regular email file and return its decoded sender and message."""
    return _eml_reader.read_path(file_path)


def read_eml_bytes(raw_email):
    """Parse bounded email bytes into a (sender, message) tuple."""
    return _eml_reader.read_bytes(raw_email)


def read_eml_header(email_message, name):
    """Decode source metadata without repairing a suspicious sender address."""
    return eml.read_eml_header(email_message, name)


def read_eml_body(email_message):
    """Return joined readable plain-text and HTML bodies in source order."""
    return eml.read_eml_body(email_message)


def decode_eml_part(body_part, allow_empty=False):
    """Decode a text MIME part using its declared charset and transfer encoding."""
    return eml.decode_eml_part(body_part, allow_empty=allow_empty)


# --- Email folder picker (added feature) ---------------------------------
# Lets the user pick a .eml file from a saved folder instead of typing a path.
# Reuses read_eml_details() above for all parsing/validation.

EML_FOLDER_KEY = "eml_folder"  # key in the local config file
EML_PAGE_SIZE = 5  # how many .eml files to show at a time


def _is_email_folder(folder: object) -> bool:
    """Check external preference/input values before constructing a filesystem path."""
    if not isinstance(folder, str) or not folder.strip():
        return False
    try:
        return Path(folder).is_dir()
    except (OSError, ValueError):
        return False


def get_eml_folder():
    """Return a usable saved folder or prompt until a valid folder is supplied.

    Attempt to save the selection. A preference-save failure produces a
    warning but does not prevent using the folder for the current import.
    """
    folder = local_settings.get_setting(EML_FOLDER_KEY)
    if _is_email_folder(folder):
        return folder

    # First run (or the saved folder is gone): ask and save.
    if folder:
        print("Saved email folder is invalid or no longer available.")
    print("First time: tell PhishReport which folder holds your .eml files.")
    while True:
        entered = input("Enter the path to your email folder: ").strip().strip('"')
        if not entered:
            print("Folder path cannot be blank.")
            continue
        if not _is_email_folder(entered):
            print("That folder does not exist. Please enter a valid folder path.")
            continue
        if local_settings.save_setting(EML_FOLDER_KEY, entered):
            print("Saved. You won't be asked again while this folder remains available.")
        else:
            print("Could not save the folder preference; using it for this selection only.")
        return entered


def list_eml_files(folder):
    """Return the folder's .eml files, newest first by modified time."""
    files = [p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() == ".eml"]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def choose_eml_file(folder):
    """Show files in pages and return the selected path, or None on cancel/no files.

    Permit selection from any page already shown. Retry invalid choices;
    propagate filesystem errors to get_eml_from_folder for user feedback.
    """
    files = list_eml_files(folder)
    if not files:
        print(f"No .eml files found in '{folder}'.")
        return None

    shown = 0
    while True:
        # Show the next page of files.
        page = files[shown : shown + EML_PAGE_SIZE]
        for index, path in enumerate(page, start=shown + 1):
            print(f"{index}. {path.name}")
        shown += len(page)

        options = "Enter a number to pick a file"
        if shown < len(files):
            options += ", 'm' for more"
        options += ", or 'c' to cancel: "
        answer = input(options).strip().lower()

        if answer == "c":
            return None
        if answer == "m" and shown < len(files):
            continue
        selected = 0
        if answer.isdigit():
            try:
                selected = int(answer)
            except ValueError:
                # Some Unicode digits and excessive-length numbers cannot be parsed.
                pass
        if 1 <= selected <= shown:
            return files[selected - 1]
        print("Invalid choice. Please try again.")


def get_eml_from_folder():
    """Return the selected email as (sender, message), or None if none is selected.

    Report directory errors and stop selection. Report individual file
    failures and allow another selection without returning partial content.
    """
    folder = get_eml_folder()
    while True:
        try:
            chosen = choose_eml_file(folder)
        except OSError:
            print("Unable to list the email folder. Check its availability and permissions.")
            return None
        if chosen is None:
            return None  # user cancelled or no files
        try:
            sender, message = read_eml_details(str(chosen))
        except (OSError, ValueError):
            print("Unable to read that email file. Please choose another.")
            print("Use a valid plain-text or HTML email. Images and attachments are not analysed.")
            continue
        print("Email loaded successfully.")
        return sender, message


def get_link_information():
    """Return (has_link, link), requiring nonblank text when a link is reported.

    Return (False, None) when absent. Collect the supplied text without
    visiting the link or validating its destination.
    """
    has_link = ask_yes_no("Was a link included? (yes/no): ")

    if not has_link:
        return False, None

    link = input("Enter the link: ").strip()

    while link == "":
        link = input("Link cannot be blank. Please enter the link: ").strip()

    return True, link


def get_file_information():
    """Return (has_file, file_name), requiring a name when a file is reported.

    Return (False, None) when absent. This question collects metadata only;
    it does not open or inspect the named file.
    """
    has_file = ask_yes_no("Was a file included? (yes/no): ")

    if not has_file:
        return False, None

    file_name = input("Enter the file name: ").strip()

    while file_name == "":
        file_name = input("File name cannot be blank. Please enter the file name: ").strip()

    return True, file_name


def get_submitted_category():
    """Return password, otp or None from the validated disclosure answer."""
    submitted = get_valid_choice(
        "Did you give a password or code? (password/otp/no): ",
        ("password", "otp", "no"),
        "Please type password, otp or no: ",
    )

    if submitted == "no":
        return None

    return submitted


def collect_user_actions(has_link, has_file):
    """Return clicked, downloaded and submitted_category from exposure questions.

    Ask about clicks/downloads only when the corresponding item was reported;
    otherwise record False. Always ask whether credentials were submitted.
    """
    if has_link:
        clicked = ask_yes_no("Did you click the link? (yes/no): ")
    else:
        clicked = False

    if has_file:
        downloaded = ask_yes_no("Did you download the file? (yes/no): ")
    else:
        downloaded = False

    submitted_category = get_submitted_category()

    return {
        "clicked": clicked,
        "downloaded": downloaded,
        "submitted_category": submitted_category,
    }


def display_result(result: dict | None) -> None:
    """Display a validated outcome or an explicit unavailable assessment."""
    if not result:
        print("\nNo assessment available.")
        return

    priority = (result.get("priority") or "unavailable").replace("_", " ").title()
    print("\n=== Assessment ===")
    print("Priority:", priority)
    print("Rule-based score:", result.get("score", "Unavailable"))

    if result.get("reasons"):
        print("\nReasons:")
        for reason in result["reasons"]:
            print(" -", reason)

    print("\nRecommended actions:")
    for number, step in enumerate(result.get("checklist", []), start=1):
        print(f"{number}. {step}")


def display_record(record: dict) -> None:
    """Display a validated saved record, preserving absent historical fields."""
    print("\n=== Report details ===")
    channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
    print("Channel:", channels.get(record.get("channel"), "Unknown"))
    print("Sender:", record.get("sender") or "Unknown")
    print("Message:")
    print(record.get("message") or "No message recorded.")
    print("Included link:", record.get("link") or "None reported")
    print("Included file:", record.get("file_name") or "None reported")

    answers = {True: "Yes", False: "No", None: "Not recorded"}
    print("Clicked link:", answers[record.get("clicked")])
    print("Downloaded file:", answers[record.get("downloaded")])
    submitted = record.get("submitted_category")
    labels = {"password": "Password", "otp": "One-time code"}
    print("Information submitted:", labels.get(submitted, submitted or "None reported"))

    display_result(record.get("result") or {})


def display_list(records: list[dict]) -> None:
    """Display validated saved summaries without altering or reassessing outcomes.

    Support nested versioned results and root-level legacy summaries. Show
    missing outcomes as unavailable and shorten only the displayed preview.
    """
    if not records:
        print("No saved reports yet.")
        return

    print("\n=== Saved reports ===")
    for number, record in enumerate(records, start=1):
        result = record.get("result") or record
        priority = (result.get("priority") or "unavailable").replace("_", " ").title()
        channels = {"email": "Email", "sms": "SMS", "chat": "Chat"}
        channel = channels.get(record.get("channel"), "Unknown")
        score = result.get("score")
        if score is None:
            score = "Unavailable"
        preview = " ".join((record.get("message") or "").split())
        if len(preview) > 50:
            preview = preview[:47] + "..."
        print(f"{number}. {channel} | {priority} | Score: {score}")
        print(f"   {preview}")


def show_message(text):
    """Print an application-supplied status or error message to the terminal."""
    print(text)
