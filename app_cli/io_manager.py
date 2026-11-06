# io_manager.py
# Console adapter and compatibility functions. OWNER: Jeremy Goh & Bryan Lee.

from io_core import IOManager, eml, folder
from io_core.manager import UPLOAD_TYPE_MESSAGE as UPLOAD_TYPE_MESSAGE
from io_core.terminal import ConsoleTerminal as ConsoleTerminal

MAX_EML_BYTES = eml.MAX_EML_BYTES
MAX_MIME_PARTS = eml.MAX_MIME_PARTS
MAX_MIME_DEPTH = eml.MAX_MIME_DEPTH
MAX_MESSAGE_CHARS = eml.MAX_MESSAGE_CHARS
EML_FOLDER_KEY = folder.EML_FOLDER_KEY
EML_PAGE_SIZE = folder.EML_PAGE_SIZE


default_io_manager = IOManager(ConsoleTerminal())


def main_menu():
    """Display the CLI menu and return a validated, normalized menu choice."""
    return default_io_manager.main_menu()


def get_valid_choice(prompt, valid_choices, error_message):
    """Prompt until stripped, lowercase input matches one of valid_choices.

    Print error_message after an invalid answer. EOF and keyboard interruption
    propagate to the main loop for a consistent application exit.
    """
    return default_io_manager.get_valid_choice(prompt, valid_choices, error_message)


def collect_input() -> dict:
    """Collect validated manual fields, then use the shared exposure questions."""
    return default_io_manager.collect_input()


def build_record_from_message(
    message: str, channel: str = "email", sender: str | None = None
) -> dict:
    """Build a record from already-obtained message text (e.g. an uploaded file).

    Manual, folder and upload collection all use this single action/record contract.
    The caller supplies message text validated by its collection or decoding path.
    """
    return default_io_manager.build_record_from_message(message, channel, sender)


def collect_input_from_upload(upload):
    """Use the folder import's MIME parser and exposure contract for browser EML."""
    return default_io_manager.collect_input_from_upload(upload)


def show_upload_instructions(host, port):
    """Print the browser upload address and waiting instructions; do not start a server."""
    default_io_manager.show_upload_instructions(host, port)


def collect_input_from_folder() -> dict | None:
    """Load a selected email and reuse the same record builder as other routes."""
    return default_io_manager.collect_input_from_folder()


def ask_yes_no(question):
    """Prompt until yes/y or no/n is entered, ignoring case and surrounding spaces.

    Return a boolean; leave cancellation handling to the application loop.
    """
    return default_io_manager.ask_yes_no(question)


def get_channel():
    """Return the user-selected channel: email, sms or chat."""
    return default_io_manager.get_channel()


def get_sender():
    """Return stripped sender text, or None for a blank answer; do not verify identity."""
    return default_io_manager.get_sender()


def get_message():
    """Prompt for a single nonblank line and return its stripped message text."""
    return default_io_manager.get_message()


def validate_mime_limits(email_message):
    """Check MIME part count, depth and rejected structural defects."""
    return eml.validate_mime_limits(email_message)


def read_eml_details(file_path):
    """Read a bounded regular email file and return its decoded sender and message."""
    return default_io_manager.eml_reader.read_path(file_path)


def read_eml_bytes(raw_email):
    """Parse bounded email bytes into a (sender, message) tuple."""
    return default_io_manager.eml_reader.read_bytes(raw_email)


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
    return default_io_manager.folder_picker.get_eml_folder()


def list_eml_files(folder):
    """Return the folder's .eml files, newest first by modified time."""
    return default_io_manager.folder_picker.list_eml_files(folder)


def choose_eml_file(folder):
    """Show files in pages and return the selected path, or None on cancel/no files."""
    return default_io_manager.folder_picker.choose_eml_file(folder)


def get_eml_from_folder():
    """Return the selected email as (sender, message), or None if none is selected."""
    return default_io_manager.folder_picker.get_eml_from_folder()


def get_link_information():
    """Return (has_link, link), requiring nonblank text when a link is reported.

    Return (False, None) when absent. Collect the supplied text without
    visiting the link or validating its destination.
    """
    return default_io_manager.get_link_information()


def get_file_information():
    """Return (has_file, file_name), requiring a name when a file is reported.

    Return (False, None) when absent. This question collects metadata only;
    it does not open or inspect the named file.
    """
    return default_io_manager.get_file_information()


def get_submitted_category():
    """Return password, otp or None from the validated disclosure answer."""
    return default_io_manager.get_submitted_category()


def collect_user_actions(has_link, has_file):
    """Return clicked, downloaded and submitted_category from exposure questions.

    Ask about clicks/downloads only when the corresponding item was reported;
    otherwise record False. Always ask whether credentials were submitted.
    """
    return default_io_manager.collect_user_actions(has_link, has_file)


def display_result(result: dict | None) -> None:
    """Display a validated outcome or an explicit unavailable assessment."""
    default_io_manager.display_result(result)


def display_record(record: dict) -> None:
    """Display a validated saved record, preserving absent historical fields."""
    default_io_manager.display_record(record)


def display_list(records: list[dict]) -> None:
    """Display validated saved summaries without altering or reassessing outcomes."""
    default_io_manager.display_list(records)


def show_message(text):
    """Print an application-supplied status or error message to the terminal."""
    default_io_manager.show_message(text)
