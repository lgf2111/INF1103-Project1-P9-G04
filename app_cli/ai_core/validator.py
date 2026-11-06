"""Validate AI completion content and its reported source details."""

import ipaddress
import json
import re

from ._diagnostics import failure
from ._json import load_strict_json

FINDING_KEYS = ("credential_request", "suspicious", "insufficient_context")


REQUIRED_KEYS = (*FINDING_KEYS, "details")


DETAIL_KEYS = ("emails", "phone_numbers", "ip_addresses")


class AIResponseValidator:
    """Parse findings and verify that returned details occur in the source text."""

    def parse_response(self, raw: str) -> dict:
        """Parse JSON text, optionally enclosed in a complete plain or json fence.

        Return an object for validate_response to check. Raise ValueError for
        non-text input, unsupported wrappers, invalid JSON or a non-object root.
        """
        if not isinstance(raw, str):
            raise failure("parse_response", "AI reply must be text.", ValueError)
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[0] not in ("```", "```json") or lines[-1] != "```":
                raise failure("parse_response", "AI reply has an invalid code fence.", ValueError)
            text = "\n".join(lines[1:-1])
        try:
            data = load_strict_json(text)
        except json.JSONDecodeError:
            raise failure("parse_response", "AI reply is not valid JSON.", ValueError) from None
        except (ValueError, RecursionError):
            raise failure(
                "parse_response",
                "AI reply contains invalid or excessively nested JSON.",
                ValueError,
            ) from None
        if not isinstance(data, dict):
            raise failure("parse_response", "AI reply must be a JSON object.", ValueError)
        return data

    def validate_response(self, data: dict) -> dict:
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
                "AI reply must contain exactly: " + ", ".join(REQUIRED_KEYS),
                ValueError,
            )
        for key in FINDING_KEYS:
            if not isinstance(data[key], bool):
                raise failure(
                    "validate_response",
                    "AI reply key is not true/false: " + key,
                    ValueError,
                )
        try:
            self._validate_detail_schema(data["details"])
        except ValueError:
            raise failure(
                "validate_response",
                "AI reply has invalid detail fields.",
                ValueError,
            ) from None
        return data

    def validate_details(self, details: dict, message: str) -> dict:
        """Validate extraction syntax and ordered, exact message occurrences unchanged.

        Matching source occurrences does not prove completeness or real-world validity.
        Failures emit one sanitised diagnostic and never include extracted values.
        """
        try:
            return self._validate_source_details(details, message)
        except ValueError:
            raise failure(
                "validate_details",
                "AI details have invalid fields or source occurrences.",
                ValueError,
            ) from None

    @staticmethod
    def _validate_detail_schema(details: dict) -> None:
        """Check the exact three detail lists and each returned value's syntax.

        Accept empty lists and repeated values. Raise ValueError for invalid
        entries; do not check reachability, ownership, reputation or completeness.
        """
        if not isinstance(details, dict) or set(details) != set(DETAIL_KEYS):
            raise ValueError("AI details must contain exactly: " + ", ".join(DETAIL_KEYS))
        formats = {
            "emails": r"[A-Za-z0-9-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]+",
            "phone_numbers": r"[0-9]{4} ?[0-9]{4}",
        }
        for key in DETAIL_KEYS:
            if not isinstance(details[key], list):
                raise ValueError("AI detail field must be a list: " + key)
            for value in details[key]:
                if not isinstance(value, str) or not value:
                    raise ValueError("AI detail entries must be nonempty strings: " + key)
                if key == "ip_addresses":
                    try:
                        ipaddress.ip_address(value)
                    except ValueError:
                        raise ValueError("AI detail has invalid IP address syntax.") from None
                elif re.fullmatch(formats[key], value) is None:
                    raise ValueError("AI detail has invalid format: " + key)

    def _validate_source_details(self, details: dict, message: str) -> dict:
        """Return unchanged details after matching exact occurrences in the message.

        Advance independently through each detail list to enforce source order
        and distinct occurrences for repeats. Raise ValueError for a mismatch;
        this checks returned values, not whether the AI found every possible value.
        """
        self._validate_detail_schema(details)
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
            for value in details[key]:
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

        return details
