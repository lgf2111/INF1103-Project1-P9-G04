"""Build a combined findings and extraction prompt from an input record."""

import json

from phishreport.ai.prompts import EXTRACTION_INSTRUCTIONS, FINDINGS_INSTRUCTIONS

from ._diagnostics import FailureDiagnostics


class PromptBuilder:
    """Turn a validated input record into the single assessment prompt."""

    METADATA_KEYS = ("sender", "link", "file_name")

    def __init__(self, diagnostics: FailureDiagnostics | None = None) -> None:
        self._diagnostics = FailureDiagnostics() if diagnostics is None else diagnostics

    def build(self, record: dict) -> str:
        """Request phishing findings and message-only extraction in one JSON object.

        Accept nonblank message text and optional sender/link/file_name text or None.
        Metadata is unverified context; paths and reported exposure stay out of the prompt.
        The input layer owns file reading and email decoding. Do not mutate the record.
        """
        message = self._message(record)
        metadata = self._metadata(record)
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

    def _message(self, record: dict) -> str:
        """Return the nonblank message text or raise a logged ValueError."""
        if not isinstance(record, dict):
            raise self._diagnostics.failure(
                "build_prompt", "AI input must be a record dictionary.", ValueError
            )
        message = record.get("message")
        if not isinstance(message, str) or not message.strip():
            raise self._diagnostics.failure(
                "build_prompt", "AI input must contain nonblank message text.", ValueError
            )
        return message

    def _metadata(self, record: dict) -> dict:
        """Return the optional text metadata present on the record."""
        metadata = {}
        for key in self.METADATA_KEYS:
            value = record.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise self._diagnostics.failure(
                        "build_prompt",
                        "AI metadata must be text or None: " + key,
                        ValueError,
                    )
                metadata[key] = value
        return metadata
