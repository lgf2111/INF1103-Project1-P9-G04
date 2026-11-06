# ai_manager.py
# API transport, prompting and validation. No domain scoring or terminal I/O.
# Required functions live here to meet the Phase 1 manager-file contract.

import http.client
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

from ai_core import AIResponseValidator
from ai_core._diagnostics import failure, logger
from ai_core._json import load_strict_json
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


# API transport and bounded retries

DEFAULT_MODEL = "openai/gpt-oss-20b"


URL = "https://api.groq.com/openai/v1/chat/completions"


MAX_RATE_LIMIT_WAIT = 5


DEFAULT_MAX_ATTEMPTS = 2


def _max_attempts():
    """Read GROQ_MAX_ATTEMPTS (>=1) at request time; fall back to the default."""
    value = os.environ.get("GROQ_MAX_ATTEMPTS")
    if value is None:
        return DEFAULT_MAX_ATTEMPTS
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS
    return parsed if parsed >= 1 else DEFAULT_MAX_ATTEMPTS


def call_api(prompt: str) -> str:
    """Return completed content with a configured bound on transient retries.

    Require nonblank prompt text, otherwise raise ValueError before configuration/HTTP.
    Preserve valid prompt text exactly as supplied.
    Raise RuntimeError for missing credentials, HTTP/connection/read failures,
    invalid provider JSON, malformed envelopes or incomplete/refused answers.
    Error messages exclude provider bodies and underlying exception details.
    Read GROQ_MODEL at request time, after the caller has loaded its environment.
    An unset model uses DEFAULT_MODEL; an explicitly blank setting is rejected.
    A timeout uses GROQ_FALLBACK_MODEL when configured, otherwise the same model.
    Other transient failures retry the same model. Up to GROQ_MAX_ATTEMPTS requests
    are sent (default 2), preserving the full prompt and settings with a 30-second
    socket timeout each. Backoff is 0.5-1.5 seconds between attempts; this is not a
    total wall-clock deadline. HTTP 429 retries only with a valid Retry-After wait of
    at most five seconds. Invalid responses and configuration errors are not retried.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise failure("call_api", "AI prompt must be nonblank text.", ValueError)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise failure("call_api", "Set the GROQ_API_KEY environment variable first.", RuntimeError)

    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    if not model.strip():
        raise failure("call_api", "GROQ_MODEL must not be blank.", RuntimeError)

    fallback_model = os.environ.get("GROQ_FALLBACK_MODEL")
    if fallback_model is not None:
        fallback_model = fallback_model.strip()
        if not fallback_model or fallback_model == model.strip():
            raise failure(
                "call_api",
                "GROQ_FALLBACK_MODEL must be nonblank and differ from GROQ_MODEL.",
                RuntimeError,
            )

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            # Reduce sampling variation; temperature zero does not guarantee that
            # separate live requests return identical findings.
            "temperature": 0,
        }
    ).encode()

    request = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            # A User-Agent is needed or the request gets blocked before it
            # reaches the API.
            "User-Agent": "phishreport/1.0",
        },
    )
    max_attempts = _max_attempts()
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            break
        except (OSError, http.client.HTTPException) as error:
            timed_out = False
            retry_delay = None
            if isinstance(error, urllib.error.HTTPError):
                retryable = error.code in (500, 502, 503, 504)
                if error.code == 429:
                    retry_delay = _rate_limit_delay(error.headers)
                    retryable = retry_delay is not None
                reason = f"AI provider returned HTTP {error.code}."
                error.close()
            else:
                cause = error.reason if isinstance(error, urllib.error.URLError) else error
                retryable = isinstance(
                    cause,
                    (
                        TimeoutError,
                        ConnectionError,
                        http.client.IncompleteRead,
                        http.client.RemoteDisconnected,
                    ),
                )
                timed_out = isinstance(cause, TimeoutError)
                reason = (
                    "The AI request timed out."
                    if timed_out
                    else "Could not complete the AI request."
                )
            if attempt == max_attempts or not retryable:
                raise failure("call_api", reason, RuntimeError) from None
            # Only fixed diagnostics are logged; never include raw exception/provider data.
            retry_model = "same_model"
            if timed_out and fallback_model is not None:
                payload = json.loads(body)
                payload["model"] = fallback_model
                request = urllib.request.Request(
                    URL,
                    data=json.dumps(payload).encode(),
                    headers=dict(request.header_items()),
                )
                retry_model = "fallback_model"
            logger.info(
                "stage=call_api attempt=%s retry=%s reason=%s", attempt, retry_model, reason
            )
            time.sleep(random.uniform(0.5, 1.5) if retry_delay is None else retry_delay)

    try:
        data = load_strict_json(raw)
    except (ValueError, RecursionError):
        raise failure("call_api", "AI provider returned invalid JSON.", RuntimeError) from None
    return _completed_content(data)


def _rate_limit_delay(headers):
    """Return a permitted Retry-After delay, or None rather than retrying too early."""
    value = headers.get("Retry-After") if headers is not None else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"[0-9]+", value):
            delay = int(value)
        else:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                return None
            delay = max(0, deadline.timestamp() - time.time())
    except (ValueError, TypeError, OverflowError):
        return None
    return delay if delay <= MAX_RATE_LIMIT_WAIT else None


def _completed_content(data):
    """Return the first completed, non-refused choice as unchanged response text.

    Validate the provider envelope before extracting content. Raise RuntimeError
    for rejected responses; content JSON/schema checks belong to later stages.
    """
    if not isinstance(data, dict) or data.get("error") is not None:
        raise failure(
            "call_api",
            "AI provider returned an invalid response envelope.",
            RuntimeError,
        )
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise failure("call_api", "AI provider response has no valid choices.", RuntimeError)
    choice = choices[0]
    if not isinstance(choice, dict):
        raise failure("call_api", "AI provider returned an invalid choice.", RuntimeError)
    if choice.get("finish_reason") != "stop":
        raise failure("call_api", "AI provider did not return a completed answer.", RuntimeError)
    message = choice.get("message")
    if not isinstance(message, dict):
        raise failure("call_api", "AI provider returned an invalid message.", RuntimeError)
    if message.get("refusal") is not None:
        raise failure("call_api", "AI provider refused the assessment.", RuntimeError)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise failure("call_api", "AI provider returned no usable response text.", RuntimeError)
    return content


# Schema and source validation


def validate_response(data: dict) -> dict:
    """Return unchanged boolean findings and syntactically valid detail lists."""
    return _DEFAULT_VALIDATOR.validate_response(data)


def validate_details(data, message):
    """Validate extraction syntax and ordered, exact message occurrences unchanged."""
    return _DEFAULT_VALIDATOR.validate_details(data, message)
