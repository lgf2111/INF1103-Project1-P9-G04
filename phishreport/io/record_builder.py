"""Derive incident-record inputs from pasted message text.

The CLI no longer asks for the channel, sender, link or file. Those values are
textual clues taken from the pasted message, so they are never presented as
verified facts: a URL is not visited and a named file is not opened.
"""

import re

EMAIL_ADDRESS = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
EMAIL_HEADER = re.compile(
    r"(?im)^(?:from|to|cc|bcc|subject|date|reply-to|return-path|received|"
    r"message-id|mime-version|content-type|content-transfer-encoding|"
    r"content-disposition):\s*\S"
)
LINK = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"']+", re.I)
PHONE_NUMBER = re.compile(
    r"(?<![\w.])(?:\+65[\s-]?\d{4}[\s-]?\d{4}|\+\d{8,15}|"
    r"[89]\d{3}[\s-]?\d{4})(?![\w.])"
)
SHORTCODE = re.compile(r"(?<![\d.])\d{5,6}(?![\d.])")
SMS_WORDING = re.compile(r"\b(?:sms|text\s+message)\b", re.I)
FILENAME = re.compile(
    r"(?<![\w.-])[\w-][\w.-]*\.(?:pdf|docx?|xlsx?|zip|apk|exe|jpe?g|png|gif|webp|eml)"
    r"(?!\w|\.\w)",
    re.I,
)
ATTACHMENT_MENTION = re.compile(
    r"\b(?:attachments?|attached\s+(?:(?:a|an|the)\s+)?(?:files?|documents?))\b",
    re.I,
)
ATTACHMENT_PART = re.compile(r"(?im)^content-disposition:\s*attachment\b")
MIME_NAME = re.compile(r"""(?i)\b(?:file)?name\*?\s*=\s*"?([^"\r\n;]+)""")


class InputDeriver:
    """Derive the record fields that a pasted message text can supply."""

    @staticmethod
    def _trim_link(link: str) -> str:
        """Drop sentence punctuation and unbalanced closing brackets from a URL."""
        extra_closing = {
            closing: link.count(closing) - link.count(opening)
            for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"))
        }
        while link:
            if link[-1] in ".,;:!?":
                link = link[:-1]
            elif extra_closing.get(link[-1], 0) > 0:
                extra_closing[link[-1]] -= 1
                link = link[:-1]
            else:
                break
        return link

    @staticmethod
    def extract_link(text: str) -> str | None:
        """Return the first URL outside an email address, or None."""
        emails = list(EMAIL_ADDRESS.finditer(text))
        for match in LINK.finditer(text):
            if any(email.start() <= match.start() < email.end() for email in emails):
                continue
            return InputDeriver._trim_link(match.group()) or None
        return None

    @staticmethod
    def _without_contacts(text: str) -> str:
        """Blank email addresses and URLs so their digits cannot look like a number."""
        spans = [match.span() for match in EMAIL_ADDRESS.finditer(text)]
        spans += [match.span() for match in LINK.finditer(text)]
        if not spans:
            return text
        characters = list(text)
        for start, end in spans:
            characters[start:end] = " " * (end - start)
        return "".join(characters)

    @staticmethod
    def extract_sender(text: str) -> str | None:
        """Return the first email address, else phone number, else None."""
        email = EMAIL_ADDRESS.search(text)
        if email:
            return email.group()
        phone = PHONE_NUMBER.search(InputDeriver._without_contacts(text))
        if phone:
            return phone.group().strip()
        return None

    @staticmethod
    def detect_channel(text: str) -> str:
        """Return email for mail text, sms for number/SMS clues, and chat otherwise."""
        if EMAIL_HEADER.search(text) or EMAIL_ADDRESS.search(text):
            return "email"
        plain = InputDeriver._without_contacts(text)
        if SMS_WORDING.search(text) or PHONE_NUMBER.search(plain) or SHORTCODE.search(plain):
            return "sms"
        return "chat"

    @staticmethod
    def extract_file(text: str) -> tuple[bool, str | None]:
        """Return (has_file, file_name) from a filename, MIME part or attachment mention."""
        excluded = [match.span() for match in EMAIL_ADDRESS.finditer(text)]
        excluded += [match.span() for match in LINK.finditer(text)]
        for match in FILENAME.finditer(text):
            if not any(
                start < match.end() and match.start() < end for start, end in excluded
            ):
                return True, match.group()
        if ATTACHMENT_PART.search(text):
            name = MIME_NAME.search(text)
            return True, name.group(1).strip() if name else None
        if ATTACHMENT_MENTION.search(text):
            return True, None
        return False, None

    @staticmethod
    def derive_inputs(text: str) -> dict:
        """Return the record fields that can be derived from the message text."""
        link = InputDeriver.extract_link(text)
        has_file, file_name = InputDeriver.extract_file(text)
        return {
            "channel": InputDeriver.detect_channel(text),
            "sender": InputDeriver.extract_sender(text),
            "has_link": link is not None,
            "link": link,
            "has_file": has_file,
            "file_name": file_name,
        }
