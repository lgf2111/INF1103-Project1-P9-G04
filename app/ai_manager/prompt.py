# ai_manager/prompt.py
# Builds the single prompt sent to the AI. OWNER: Pair A.

import json

from .errors import failure
from .prompts import EXTRACTION_INSTRUCTIONS, FINDINGS_INSTRUCTIONS


def build_prompt(record: dict) -> str:
    """Request phishing findings and message-only extraction in one JSON object.

    Accept nonblank message text and optional sender/link/file_name text or None.
    Metadata is unverified context; paths and reported exposure stay out of the prompt.
    The input layer owns file reading and email decoding. Do not mutate the record.
    """
    if not isinstance(record, dict):
        raise failure("build_prompt", "AI input must be a record dictionary.", ValueError)
    message = record.get("message")
    if not isinstance(message, str) or not message.strip():
        raise failure("build_prompt", "AI input must contain nonblank message text.", ValueError)
    metadata = {}
    for key in ("sender", "link", "file_name"):
        value = record.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise failure(
                    "build_prompt", "AI metadata must be text or None: " + key, ValueError,
                )
            metadata[key] = value
    return (
        FINDINGS_INSTRUCTIONS
        + EXTRACTION_INSTRUCTIONS
        + "Metadata (JSON object):\n" + json.dumps(metadata) + "\n"
        + "Message (JSON string):\n" + json.dumps(message)
    )
