"""Coordinate one validated AI assessment."""

from .client import AIClient
from .groq_client import GroqClient
from .prompt import PromptBuilder
from .validator import AIResponseValidator


class AIManager:
    """Build prompts and validate completions through an injectable client."""

    def __init__(
        self, client: AIClient | None = None, prompt_builder: PromptBuilder | None = None
    ) -> None:
        self._client: AIClient = GroqClient() if client is None else client
        self._prompt_builder = PromptBuilder() if prompt_builder is None else prompt_builder
        self._validator = AIResponseValidator()

    def assess(self, record: dict) -> dict:
        """Return validated findings, propagating input, reply or client failures."""
        prompt = self._prompt_builder.build(record)
        raw = self._client.complete(prompt)
        reply = self._validator.parse_response(raw)
        findings = self._validator.validate_response(reply)
        self._validator.validate_details(findings["details"], record["message"])
        return findings
