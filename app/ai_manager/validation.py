# ai_manager/validation.py
# Validates the AI reply's schema and extracted details. OWNER: Pair A.

import ipaddress
import re

from .errors import failure

# The keys we expect back from the AI.
FINDING_KEYS = ("credential_request", "suspicious", "insufficient_context")
REQUIRED_KEYS = (*FINDING_KEYS, "details")
DETAIL_KEYS = ("emails", "phone_numbers", "ip_addresses")


def validate_response(data: dict) -> dict:
    """Return unchanged boolean findings and syntactically valid detail lists.

    Reject malformed roots, missing/extra keys, wrong types and invalid detail syntax.
    validate_details separately checks source occurrences against the original message.
    The logic layer interprets the findings; validation does not decide priority.
    """
    if not isinstance(data, dict):
        raise failure("validate_response", "AI reply must be a JSON object.", ValueError)
    if set(data) != set(REQUIRED_KEYS):
        raise failure(
            "validate_response",
            "AI reply must contain exactly: " + ", ".join(REQUIRED_KEYS), ValueError,
        )
    for key in FINDING_KEYS:
        if not isinstance(data[key], bool):
            raise failure(
                "validate_response", "AI reply key is not true/false: " + key, ValueError,
            )
    try:
        _validate_detail_schema(data["details"])
    except ValueError:
        raise failure(
            "validate_response", "AI reply has invalid detail fields.", ValueError,
        ) from None
    return data


def validate_details(data, message):
    """Validate extraction syntax and ordered, exact message occurrences unchanged.

    Matching source occurrences does not prove completeness or real-world validity.
    Failures emit one sanitised diagnostic and never include extracted values.
    """
    try:
        return _validate_source_details(data, message)
    except ValueError:
        raise failure(
            "validate_details", "AI details have invalid fields or source occurrences.", ValueError,
        ) from None


def _validate_detail_schema(data):
    """Check the shared extraction shape and syntax without needing source text."""
    if not isinstance(data, dict) or set(data) != set(DETAIL_KEYS):
        raise ValueError("AI details must contain exactly: " + ", ".join(DETAIL_KEYS))
    formats = {
        "emails": r"[A-Za-z0-9-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]+",
        "phone_numbers": r"[0-9]{4} ?[0-9]{4}",
    }
    for key in DETAIL_KEYS:
        if not isinstance(data[key], list):
            raise ValueError("AI detail field must be a list: " + key)
        for value in data[key]:
            if not isinstance(value, str) or not value:
                raise ValueError("AI detail entries must be nonempty strings: " + key)
            if key == "ip_addresses":
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    raise ValueError("AI detail has invalid IP address syntax.") from None
            elif re.fullmatch(formats[key], value) is None:
                raise ValueError("AI detail has invalid format: " + key)


def _validate_source_details(data, message):
    """Check returned occurrences using the existing extraction boundaries."""
    _validate_detail_schema(data)
    if not isinstance(message, str):
        raise ValueError("The original message must be text.")

    boundaries = {
        "emails": (r"(?<![\w.!#$%&'*+/=?^`{|}~@-])", r"(?![\w@-]|\.[A-Za-z0-9])"),
        "phone_numbers": (r"(?<![\w@])", r"(?![\w@])"),
        # Allow an IP label's colon while excluding prefixes within larger addresses.
        "ip_addresses": (
            r"(?:(?<![\w:.%])|(?<=\b[Ii][Pp]:))",
            r"(?![\w:%]|\.[0-9])",
        ),
    }
    # Exclude phone substrings inside email tokens, including domain labels.
    email_spans = [
        match.span() for match in re.finditer(r"[\w.!#$%&'*+/=?^`{|}~+-]+@[\w.-]+", message)
    ]

    for key in DETAIL_KEYS:
        # Advance through distinct source occurrences to preserve order and repeats.
        position = 0
        for value in data[key]:
            # Match the AI's exact text without normalizing or supplying a value.
            before, after = boundaries[key]
            if key == "phone_numbers" and " " in value:
                # Allow joined prose after grouped phones, but reject longer numbers.
                before += r"(?<![0-9] )"
                after = r"(?![\d@]| [0-9])"
            elif key == "ip_addresses" and ipaddress.ip_address(value).version == 4:
                # IPv4 can touch prose; extra digits or address segments cannot follow.
                after = r"(?![\d_:%]|\.[0-9])"
            occurrence = re.compile(before + re.escape(value) + after)
            for match in occurrence.finditer(message, position):
                if key == "phone_numbers" and any(
                    start <= match.start() and match.end() <= end for start, end in email_spans
                ):
                    continue
                position = match.end()
                break
            else:
                raise ValueError("AI detail has no matching source occurrence in order: " + key)

    return data
