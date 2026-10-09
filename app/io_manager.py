# io_manager.py
# All input() and print() live here. OWNER: Jeremy Goh & Bryan Lee.

import os
import stat
from email import policy
from email.errors import (
    CloseBoundaryNotFoundDefect,
    InvalidBase64CharactersDefect,
    InvalidBase64PaddingDefect,
    MissingHeaderBodySeparatorDefect,
)
from email.parser import BytesParser
from pathlib import Path

MAX_EML_BYTES = 2 * 1024 * 1024
MAX_MIME_PARTS = 100
MAX_MIME_DEPTH = 32
MAX_MESSAGE_CHARS = 50_000

def main_menu():
    print("\n=== PhishReport ===")
    print("1. Check a new message")
    print("2. View saved reports")
    print("3. Quit")

    return get_valid_choice(
        "Choose 1-3: ",
        ("1", "2", "3"),
        "Invalid choice. Please choose 1-3: ",
    )

def get_valid_choice(prompt, valid_choices, error_message):
    choice = input(prompt).strip().lower()

    while choice not in valid_choices:
        choice = input(error_message).strip().lower()

    return choice

def collect_input():
    channel = get_channel()

    if channel == "email":
        method = get_valid_choice(
            "Choose email input method (1 = Manual, 2 =.eml file): ",
            ("1", "2"),
            "Invalid choice. Please enter 1 or 2: ",
        )

        if method == "2":
            sender, message = get_eml_input()
        else:
            sender = get_sender()
            message = get_message()
    else:
        sender = get_sender()
        message = get_message()

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

def ask_yes_no(question):
    answer = input(question).strip().lower()

    while answer not in ("y", "yes", "n", "no"):
        answer = input("Please type yes/y or no/n: ").strip().lower()

    return answer in ("y", "yes")

def get_channel():
    return get_valid_choice(
        "Enter channel (Email/SMS/Chat): ",
        ("email", "sms", "chat"),
        "Invalid channel. Please enter Email, SMS, or Chat: ",
    )

def get_sender():
    sender = input(
        "Enter sender information (press Enter if unknown): "
    ).strip()

    if sender == "":
        return None

    return sender

def get_message():
    message = input("Enter the suspicious message: ").strip()

    while message == "":
        message = input(
            "Message cannot be blank. Please enter the suspicious message: "
        ).strip()

    return message

def validate_mime_limits(email_message):
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
    with Path(file_path).open("rb") as email_file:

        # Ensure the opened path is a regular file.
        file_info = os.fstat(email_file.fileno())

        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError("Email path must be a regular file.")

        # Read only up to the maximum allowed size + 1 byte.
        raw_email = email_file.read(MAX_EML_BYTES + 1)

    # Reject email files larger than 2 MiB.
    if len(raw_email) > MAX_EML_BYTES:
        raise ValueError("Email file exceeds the size limit.")

    # Parse the email and validate its MIME structure.
    try:
        email_message = BytesParser(
            policy=policy.default
        ).parsebytes(raw_email)

        # Validate MIME part count and nesting depth.
        validate_mime_limits(email_message)

        # Extract the plain-text email body.
        body_part = email_message.get_body(
            preferencelist=("plain",)
        )

    except RecursionError as error:
        raise ValueError(
            "Email MIME structure is too deeply nested."
        ) from error

    # Check for duplicate From headers.
    from_headers = email_message.get_all("From", [])

    if len(from_headers) > 1:
        raise ValueError("Duplicate From header detected.")

    # Check for duplicate Subject headers.
    subject_headers = email_message.get_all("Subject", [])

    if len(subject_headers) > 1:
        raise ValueError("Duplicate Subject header detected.")

    # Extract the sender and subject.
    sender = str(email_message.get("From") or "").strip() or None
    subject = str(email_message.get("Subject") or "").strip()

    # Reject emails without a readable plain-text body.
    if body_part is None:
        raise ValueError("No readable plain-text message found.")

    try:
        body = body_part.get_content()

    except RecursionError as error:
        raise ValueError(
            "Email MIME structure is too deeply nested."
        ) from error

    except (UnicodeError, LookupError) as error:
        raise ValueError(
            "Could not decode email content."
        ) from error

    # Check for invalid Base64 characters after decoding.
    # Check for invalid Base64 characters or padding after decoding.
    for defect in body_part.defects:
        if isinstance(
            defect,
            (InvalidBase64CharactersDefect, InvalidBase64PaddingDefect),
        ):
            raise ValueError("Invalid Base64 content detected.")
    # Reject empty messages.
    if not isinstance(body, str) or not body.strip():
        raise ValueError("Email message cannot be blank.")

    # Normalize Windows and other line endings.
    message = body.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Include the subject in the message for analysis.
    if subject:
        message = f"Subject: {subject}\n\n{message}"

    # Reject messages exceeding 50,000 characters.
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("Email exceeds the message length limit.")

    return sender, message

def get_eml_input():
    while True:
        file_path = input("Enter .eml file path: ").strip().strip('"')

        if not file_path:
            print("File path cannot be blank.")
            continue

        if Path(file_path).suffix.lower() != ".eml":
            print("Invalid file type. Only .eml files are supported.")
            continue

        try:
            sender, message = read_eml_details(file_path)

        except (OSError, ValueError):
            print("Unable to read the email file. Please try again.")
            continue

        print("Email loaded successfully.")

        return sender, message


def get_link_information():
    has_link = ask_yes_no("Was a link included? (yes/no): ")

    if not has_link:
        return False, None

    link = input("Enter the link: ").strip()

    while link == "":
        link = input(
            "Link cannot be blank. Please enter the link: "
        ).strip()

    return True, link

def get_file_information():
    has_file = ask_yes_no("Was a file included? (yes/no): ")

    if not has_file:
        return False, None

    file_name = input("Enter the file name: ").strip()

    while file_name == "":
        file_name = input(
            "File name cannot be blank. Please enter the file name: "
        ).strip()

    return True, file_name

def get_submitted_category():
    submitted = get_valid_choice(
        "Did you give a password or code? (password/otp/no): ",
        ("password", "otp", "no"),
        "Please type password, otp or no: ",
    )

    if submitted == "no":
        return None

    return submitted

def collect_user_actions(has_link, has_file):
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

def display_result(result):
    if not result:
        print("\nNo assessment available.")
        return

    priority = (result.get("priority") or "unavailable").replace(
        "_", " "
    ).title()
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


def display_record(record):
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


def display_list(records):
    if not records:
        print("No saved reports yet.")
        return

    print("\n=== Saved reports ===")
    for number, record in enumerate(records, start=1):
        result = record.get("result") or record
        priority = (result.get("priority") or "unavailable").replace(
            "_", " "
        ).title()
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
    print(text)
