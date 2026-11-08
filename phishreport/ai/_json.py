"""Strict JSON decoding for provider envelopes and completion content."""

import json


def _unique_object(pairs):
    """Build a JSON object without silently accepting duplicate field names."""
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("AI reply contains duplicate JSON fields.")
        data[key] = value
    return data


def _reject_constant(value):
    """Reject NaN and infinity, which Python accepts but JSON does not."""
    raise ValueError("AI reply contains a non-JSON numeric constant.")


def load_strict_json(raw: str | bytes):
    """Decode JSON while rejecting duplicate fields and non-JSON constants."""
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
