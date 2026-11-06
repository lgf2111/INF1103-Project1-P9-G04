# ai_manager.py
# Compatibility functions for AI assessment.
# Required functions live here to meet the Phase 1 manager-file contract.

from ai_core import AIResponseValidator, GroqClient
from ai_core.groq_client import DEFAULT_MAX_ATTEMPTS as DEFAULT_MAX_ATTEMPTS
from ai_core.groq_client import DEFAULT_MODEL as DEFAULT_MODEL
from ai_core.groq_client import MAX_RATE_LIMIT_WAIT as MAX_RATE_LIMIT_WAIT
from ai_core.groq_client import URL as URL
from ai_core.prompt import build_prompt as _build_prompt
from ai_core.validator import DETAIL_KEYS as DETAIL_KEYS
from ai_core.validator import FINDING_KEYS as FINDING_KEYS
from ai_core.validator import REQUIRED_KEYS as REQUIRED_KEYS
from ai_prompts import EXTRACTION_INSTRUCTIONS as EXTRACTION_INSTRUCTIONS
from ai_prompts import FINDINGS_INSTRUCTIONS as FINDINGS_INSTRUCTIONS

_DEFAULT_VALIDATOR = AIResponseValidator()


def parse_response(raw: str) -> dict:
    """Parse JSON text, optionally enclosed in a complete plain or json fence."""
    return _DEFAULT_VALIDATOR.parse_response(raw)


# Prompt construction


def build_prompt(record: dict) -> str:
    """Request phishing findings and message-only extraction in one JSON object."""
    return _build_prompt(record)


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
