# ai_manager.py
# Prompt construction and compatibility functions. No domain scoring or terminal I/O.
# Required functions live here to meet the Phase 1 manager-file contract.

import json

from ai_core import AIResponseValidator, GroqClient
from ai_core._diagnostics import failure
from ai_core.groq_client import DEFAULT_MAX_ATTEMPTS as DEFAULT_MAX_ATTEMPTS
from ai_core.groq_client import DEFAULT_MODEL as DEFAULT_MODEL
from ai_core.groq_client import MAX_RATE_LIMIT_WAIT as MAX_RATE_LIMIT_WAIT
from ai_core.groq_client import URL as URL
from ai_core.validator import DETAIL_KEYS as DETAIL_KEYS
from ai_core.validator import FINDING_KEYS as FINDING_KEYS
from ai_core.validator import REQUIRED_KEYS as REQUIRED_KEYS
from ai_prompts import EXTRACTION_INSTRUCTIONS, FINDINGS_INSTRUCTIONS

_DEFAULT_VALIDATOR = AIResponseValidator()


def parse_response(raw: str) -> dict:
    """Parse JSON text, optionally enclosed in a complete plain or json fence."""
    return _DEFAULT_VALIDATOR.parse_response(raw)


# Prompt construction


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
                    "build_prompt",
                    "AI metadata must be text or None: " + key,
                    ValueError,
                )
            metadata[key] = value
    # JSON encoding preserves source text and separates it from instruction formatting.
    return (
        FINDINGS_INSTRUCTIONS
        + EXTRACTION_INSTRUCTIONS
        + "Metadata (JSON object):\n"
        + json.dumps(metadata)
        + "\n"
        + "Message (JSON string):\n"
        + json.dumps(message)
    )


def call_api(prompt: str) -> str:
    """Return the completed provider response text for a nonblank prompt."""
    return GroqClient().complete(prompt)


# Schema and source validation


def validate_response(data: dict) -> dict:
    """Return unchanged boolean findings and syntactically valid detail lists."""
    return _DEFAULT_VALIDATOR.validate_response(data)


def validate_details(data, message):
    """Validate extraction syntax and ordered, exact message occurrences unchanged."""
    return _DEFAULT_VALIDATOR.validate_details(data, message)
