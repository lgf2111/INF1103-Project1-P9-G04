# ai_manager/parsing.py
# Parses the AI's JSON reply, including the strict JSON hooks. OWNER: Pair A.

import json

from .errors import failure


def unique_object(pairs):
    """Build a JSON object without silently accepting duplicate field names."""
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("AI reply contains duplicate JSON fields.")
        data[key] = value
    return data


def reject_constant(value):
    """Reject NaN and infinity, which Python accepts but JSON does not."""
    raise ValueError("AI reply contains a non-JSON numeric constant.")


def parse_response(raw: str) -> dict:
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
        data = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except json.JSONDecodeError:
        raise failure("parse_response", "AI reply is not valid JSON.", ValueError) from None
    except ValueError:
        raise failure(
            "parse_response", "AI reply contains invalid JSON fields or constants.", ValueError,
        ) from None
    if not isinstance(data, dict):
        raise failure("parse_response", "AI reply must be a JSON object.", ValueError)
    return data
