# io_manager.py
# All input() and print() live here. OWNER: Jeremy Goh & Bryan Lee.

import base64
import binascii
import os
import re
import stat
from email import policy
from email.errors import (
    CloseBoundaryNotFoundDefect,
    HeaderParseError,
    InvalidBase64CharactersDefect,
    InvalidBase64LengthDefect,
    InvalidBase64PaddingDefect,
    MissingHeaderBodySeparatorDefect,
)
from email.header import decode_header
from email.parser import BytesParser
from pathlib import Path

import local_settings
from email_html import html_to_text

MAX_EML_BYTES = 2 * 1024 * 1024
MAX_MIME_PARTS = 100
MAX_MIME_DEPTH = 32
MAX_MESSAGE_CHARS = 50_000
UPLOAD_TYPE_MESSAGE = (
    "Only .eml email files are supported. Images and attachments are not analysed."
)


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
    """Check MIME part count, nesting depth and selected structural defects.

    Walk iteratively to bound traversal of untrusted email input. Return None
    when accepted; raise ValueError on a limit violation or rejected defect.
    """
    stack = [(email_message, 0)]
    part_count = 0

    while stack:
        part, depth = stack.pop()
        part_count += 1

        # Reject emails containing more than 100 MIME parts.
        if part_count > MAX_MIME_PARTS:
            raise ValueError("Email has too many MIME parts.")

        # Reject MIME nesting deeper than 32 levels.
        if depth > MAX_MIME_DEPTH:
            raise ValueError("Email MIME nesting is too deep.")

        # Reject malformed MIME structures.
        for defect in part.defects:
            if isinstance(
                defect,
                (
                    CloseBoundaryNotFoundDefect,
                    MissingHeaderBodySeparatorDefect,
                ),
            ):
                raise ValueError("Malformed MIME structure detected.")

        # Inspect child MIME parts without recursion.
        if part.is_multipart():
            for child in part.iter_parts():
                stack.append((child, depth + 1))


def read_eml_details(file_path):
    """Read a bounded regular email file and return its decoded sender and message.

    Verify the opened descriptor is a regular file before reading. Delegate
    MIME validation to read_eml_bytes; propagate OSError or ValueError to the
    input flow so it can report the failure and offer another selection.
    """
    path = Path(file_path)
    if not path.is_file():
        raise ValueError("Email path must be a regular file.")

    # Nonblocking open also covers a path replaced with a FIFO after is_file().
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as email_file:
        # Ensure the opened path is a regular file.
        file_info = os.fstat(email_file.fileno())

        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError("Email path must be a regular file.")

        # Read only up to the maximum allowed size + 1 byte.
        raw_email = email_file.read(MAX_EML_BYTES + 1)

    return read_eml_bytes(raw_email)


def read_eml_bytes(raw_email):
    """Parse bounded email bytes into a (sender, message) tuple.

    Validate MIME structure and reject duplicate From or Subject headers.
    Include a decoded subject when present, normalize body line endings,
    and enforce the final message limit. Missing sender becomes None.
    Raise ValueError for rejected input; no files or URLs are opened here.
    """
    # Reject email files larger than 2 MiB.
    if len(raw_email) > MAX_EML_BYTES:
        raise ValueError("Email file exceeds the size limit.")

    # Parse the email and validate its MIME structure.
    try:
        email_message = BytesParser(policy=policy.default).parsebytes(raw_email)

        # Validate MIME part count and nesting depth.
        validate_mime_limits(email_message)

    except RecursionError as error:
        raise ValueError("Email MIME structure is too deeply nested.") from error

    # Check for duplicate From headers.
    from_headers = email_message.get_all("From", [])

    if len(from_headers) > 1:
        raise ValueError("Duplicate From header detected.")

    # Check for duplicate Subject headers.
    subject_headers = email_message.get_all("Subject", [])

    if len(subject_headers) > 1:
        raise ValueError("Duplicate Subject header detected.")

    # Extract the sender and subject.
    sender = read_eml_header(email_message, "From") or None
    subject = read_eml_header(email_message, "Subject")

    body = read_eml_body(email_message)

    # Normalize Windows and other line endings.
    message = body.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Include the subject in the message for analysis.
    if subject:
        message = f"Subject: {subject}\n\n{message}"

    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("Email exceeds the message length limit.")

    return sender, message


def read_eml_header(email_message, name):
    """Decode source metadata strictly; do not repair a suspicious sender address."""
    raw = next(
        (value for key, value in email_message.raw_items() if key.lower() == name.lower()), ""
    )
    try:
        decoded = []
        for word in re.finditer(r"=\?[^?]+\?([bBqQ])\?([^?]*)\?=", raw):
            encoding, payload = word.groups()
            if encoding.lower() == "b":
                base64.b64decode(payload, validate=True)
            elif re.search(r"=(?![0-9a-fA-F]{2})", payload):
                raise ValueError("Malformed encoded email header.")
        for value, charset in decode_header(raw):
            if isinstance(value, bytes):
                decoded.append(value.decode(charset or "ascii", errors="strict"))
            else:
                decoded.append(value.encode("utf-8", errors="surrogateescape").decode("utf-8"))
    except (UnicodeError, LookupError, HeaderParseError, binascii.Error) as error:
        raise ValueError("Could not decode email header.") from error
    # A forged/non-RFC From value is still useful untrusted evidence. Preserve
    # it as text instead of converting it to '<>' or treating it as verified.
    return re.sub(r"\r?\n[ \t]+", " ", "".join(decoded)).strip()


def read_eml_body(email_message):
    """Return joined readable plain-text and HTML bodies in source order.

    Retain both representations of alternatives for assessment. Skip
    attachments and inline images; reject unsupported body types, empty
    output or excessive text with ValueError. HTML targets remain text.
    """
    bodies = []
    had_html = False
    stack = [email_message]
    while stack:
        part = stack.pop()
        disposition = part.get_content_disposition()
        if disposition == "attachment" or (disposition is None and part.get_filename()):
            continue
        if part.get_content_maintype() == "multipart":
            if part.get_content_subtype() not in ("mixed", "alternative", "related"):
                raise ValueError("Unsupported multipart email body.")
            stack.extend(reversed(list(part.iter_parts())))
            continue
        if part.get_content_maintype() == "image":
            continue  # Inline image bytes are excluded in every supported container.
        if part.get_content_type() not in ("text/plain", "text/html"):
            raise ValueError("Unsupported email body type.")
        decoded = decode_eml_part(part, allow_empty=True)
        if not decoded.strip():
            continue
        if part.get_content_type() == "text/html":
            had_html = True
            converted = html_to_text(decoded, MAX_MESSAGE_CHARS, allow_empty=True)
            if not converted:
                continue  # Empty markup must not block another usable representation.
            decoded = "[HTML body]\n" + converted
        bodies.append(decoded)
        if sum(map(len, bodies)) + 2 * (len(bodies) - 1) > MAX_MESSAGE_CHARS:
            raise ValueError("Email exceeds the message length limit.")
    if not bodies:
        if had_html:
            raise ValueError("Email HTML has no usable text or link targets.")
        raise ValueError("No readable email message found.")
    return "\n\n".join(bodies)


def decode_eml_part(body_part, allow_empty=False):
    """Decode a text MIME part using its declared charset and transfer encoding.

    Reject unsupported or malformed encodings and non-text payloads with
    ValueError. Return stripped text; allow an empty result only when
    allow_empty is True so the caller can combine multipart content.
    """
    # The shared decoder handles both plain-text and HTML parts.
    if body_part is None:
        raise ValueError("No readable plain-text message found.")

    transfer = str(body_part.get("Content-Transfer-Encoding", "7bit")).strip().lower()
    if transfer not in ("7bit", "8bit", "binary", "base64", "quoted-printable"):
        raise ValueError("Unsupported email transfer encoding.")
    if transfer == "quoted-printable" and re.search(
        r"=(?![0-9a-fA-F]{2}|\r?\n)",
        body_part.get_payload(),
    ):
        raise ValueError("Malformed quoted-printable content.")

    try:
        body = body_part.get_content(errors="strict")

    except RecursionError as error:
        raise ValueError("Email MIME structure is too deeply nested.") from error

    except (UnicodeError, LookupError) as error:
        raise ValueError("Could not decode email content.") from error

    # Decoding records defects rather than necessarily raising an exception.
    for defect in body_part.defects:
        if isinstance(
            defect,
            (InvalidBase64CharactersDefect, InvalidBase64PaddingDefect, InvalidBase64LengthDefect),
        ):
            raise ValueError("Invalid Base64 content detected.")
    # Reject empty messages.
    if not isinstance(body, str) or (not allow_empty and not body.strip()):
        raise ValueError("Email message cannot be blank.")

    return body.strip()


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
