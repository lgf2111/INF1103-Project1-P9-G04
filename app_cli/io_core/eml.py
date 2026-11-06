"""Bounded file reads and MIME decoding for saved or uploaded email."""

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

from email_html import html_to_text

MAX_EML_BYTES = 2 * 1024 * 1024
MAX_MIME_PARTS = 100
MAX_MIME_DEPTH = 32
MAX_MESSAGE_CHARS = 50_000


class EmlReader:
    """Decode email from a regular file or in-memory bytes."""

    def read_path(self, file_path: str | os.PathLike[str]) -> tuple[str | None, str]:
        """Read a bounded regular email file and return its decoded sender and message.

        Verify the opened descriptor is a regular file before reading. Delegate
        MIME validation to read_bytes; propagate OSError or ValueError to the
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

        return self.read_bytes(raw_email)

    def read_bytes(self, raw_email: bytes) -> tuple[str | None, str]:
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
