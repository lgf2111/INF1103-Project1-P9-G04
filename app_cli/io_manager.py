# io_manager.py
# All input() and print() live here. OWNER: Jeremy Goh & Bryan Lee.

from io_core import EmlFolderPicker, EmlReader, ReportPresenter, eml, folder

MAX_EML_BYTES = eml.MAX_EML_BYTES
MAX_MIME_PARTS = eml.MAX_MIME_PARTS
MAX_MIME_DEPTH = eml.MAX_MIME_DEPTH
MAX_MESSAGE_CHARS = eml.MAX_MESSAGE_CHARS
EML_FOLDER_KEY = folder.EML_FOLDER_KEY
EML_PAGE_SIZE = folder.EML_PAGE_SIZE
UPLOAD_TYPE_MESSAGE = (
    "Only .eml email files are supported. Images and attachments are not analysed."
)


class ConsoleTerminal:
    """Connect the terminal contract to the standard console."""

    def read(self, prompt: str) -> str:
        return input(prompt)

    def write(self, *parts: object) -> None:
        print(*parts)


_terminal = ConsoleTerminal()
_eml_reader = EmlReader()
_folder_picker = EmlFolderPicker(_terminal, _eml_reader)
_presenter = ReportPresenter(_terminal)


def main_menu():
    """Display the CLI menu and return a validated, normalized menu choice."""
    _terminal.write("\n=== PhishReport ===")
    _terminal.write("1. Check a new message (Manual Input)")
    _terminal.write("2. Import an email (.eml file)")
    _terminal.write("3. Upload an email (.eml file)")
    _terminal.write("4. View saved reports")
    _terminal.write("5. Quit")

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
    choice = _terminal.read(prompt).strip().lower()

    while choice not in valid_choices:
        choice = _terminal.read(error_message).strip().lower()

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
    _terminal.write(f"\nOpen http://{host}:{port} in your browser to upload an .eml email.")
    _terminal.write("Waiting for upload... (Ctrl+C to cancel)")


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
    answer = _terminal.read(question).strip().lower()

    while answer not in ("y", "yes", "n", "no"):
        answer = _terminal.read("Please type yes/y or no/n: ").strip().lower()

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
    sender = _terminal.read("Enter sender information (press Enter if unknown): ").strip()

    if sender == "":
        return None

    return sender


def get_message():
    """Prompt for a single nonblank line and return its stripped message text."""
    message = _terminal.read("Enter the suspicious message: ").strip()

    while message == "":
        message = _terminal.read(
            "Message cannot be blank. Please enter the suspicious message: "
        ).strip()

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


def get_eml_folder():
    """Return a usable saved folder or prompt until a valid folder is supplied."""
    return _folder_picker.get_eml_folder()


def list_eml_files(folder):
    """Return the folder's .eml files, newest first by modified time."""
    return _folder_picker.list_eml_files(folder)


def choose_eml_file(folder):
    """Show files in pages and return the selected path, or None on cancel/no files."""
    return _folder_picker.choose_eml_file(folder)


def get_eml_from_folder():
    """Return the selected email as (sender, message), or None if none is selected."""
    return _folder_picker.get_eml_from_folder()


def get_link_information():
    """Return (has_link, link), requiring nonblank text when a link is reported.

    Return (False, None) when absent. Collect the supplied text without
    visiting the link or validating its destination.
    """
    has_link = ask_yes_no("Was a link included? (yes/no): ")

    if not has_link:
        return False, None

    link = _terminal.read("Enter the link: ").strip()

    while link == "":
        link = _terminal.read("Link cannot be blank. Please enter the link: ").strip()

    return True, link


def get_file_information():
    """Return (has_file, file_name), requiring a name when a file is reported.

    Return (False, None) when absent. This question collects metadata only;
    it does not open or inspect the named file.
    """
    has_file = ask_yes_no("Was a file included? (yes/no): ")

    if not has_file:
        return False, None

    file_name = _terminal.read("Enter the file name: ").strip()

    while file_name == "":
        file_name = _terminal.read(
            "File name cannot be blank. Please enter the file name: "
        ).strip()

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
    _presenter.display_result(result)


def display_record(record: dict) -> None:
    """Display a validated saved record, preserving absent historical fields."""
    _presenter.display_record(record)


def display_list(records: list[dict]) -> None:
    """Display validated saved summaries without altering or reassessing outcomes."""
    _presenter.display_list(records)


def show_message(text):
    """Print an application-supplied status or error message to the terminal."""
    _terminal.write(text)
