# ai_manager package (public API)
# Talks to the Groq API (free tier). No business rules here. OWNER: Pair A.
#
# Every message goes through here - this is the core of the app. The package is
# split into focused modules; this file just exposes the public functions and
# names the rest of the app (and tests) use:
#
#   prompt.py      build_prompt
#   client.py      call_api  (HTTP transport to Groq)
#   parsing.py     parse_response
#   validation.py  validate_response, validate_details
#   errors.py      shared failure logging
#   prompts.py     the prompt text

# Re-exported so patching ai_manager.urllib.request.urlopen still works in tests.
import urllib

from .client import DEFAULT_MODEL, URL, call_api
from .errors import logger
from .parsing import parse_response
from .prompt import build_prompt
from .prompts import EXTRACTION_INSTRUCTIONS, FINDINGS_INSTRUCTIONS
from .validation import (
    DETAIL_KEYS,
    FINDING_KEYS,
    REQUIRED_KEYS,
    validate_details,
    validate_response,
)

__all__ = [
    "build_prompt",
    "call_api",
    "parse_response",
    "validate_response",
    "validate_details",
    "DEFAULT_MODEL",
    "URL",
    "FINDING_KEYS",
    "REQUIRED_KEYS",
    "DETAIL_KEYS",
    "EXTRACTION_INSTRUCTIONS",
    "FINDINGS_INSTRUCTIONS",
    "logger",
    "urllib",
]
