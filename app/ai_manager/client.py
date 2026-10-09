# ai_manager/client.py
# HTTP transport to the Groq API. No business rules here. OWNER: Pair A.
#
# Uses only the Python standard library (urllib) so there is nothing extra to
# install. The API key is read from the GROQ_API_KEY environment variable so it
# is never written into the code.
#
# Get a free key at https://console.groq.com (no credit card needed).

import http.client
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

from .errors import failure, logger
from .parsing import reject_constant, unique_object

# Groq's API is OpenAI-style. Change the model with the GROQ_MODEL env var.
# (Run the /models endpoint or check the Groq console to see what your key can use.)
DEFAULT_MODEL = "openai/gpt-oss-20b"
URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RATE_LIMIT_WAIT = 5


def call_api(prompt: str) -> str:
    """Return completed content, retrying a transient transport failure once.

    Require nonblank prompt text, otherwise raise ValueError before configuration/HTTP.
    Preserve valid prompt text exactly as supplied.
    Raise RuntimeError for missing credentials, HTTP/connection/read failures,
    invalid provider JSON, malformed envelopes or incomplete/refused answers.
    Error messages exclude provider bodies and underlying exception details.
    Read GROQ_MODEL at request time, after the caller has loaded its environment.
    An unset model uses DEFAULT_MODEL; an explicitly blank setting is rejected.
    A timeout uses GROQ_FALLBACK_MODEL when configured, otherwise the same model.
    Other transient failures retry the same model. At most two requests are sent,
    preserving the full prompt and settings with a 30-second socket timeout each.
    Backoff is 0.5-1.5 seconds; this is not a total wall-clock deadline.
    HTTP 429 retries only with a valid Retry-After wait of at most five seconds.
    Invalid responses and configuration errors are not retried.
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
                "call_api", "GROQ_FALLBACK_MODEL must be nonblank and differ from GROQ_MODEL.",
                RuntimeError,
            )

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        # temperature 0 keeps replies deterministic so the same input gives the
        # same findings and the strict JSON contract is less likely to drift.
        "temperature": 0,
    }).encode()

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
    for attempt in (1, 2):
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
                retryable = isinstance(cause, (
                    TimeoutError, ConnectionError, http.client.IncompleteRead,
                    http.client.RemoteDisconnected,
                ))
                timed_out = isinstance(cause, TimeoutError)
                reason = ("The AI request timed out." if timed_out
                          else "Could not complete the AI request.")
            if attempt == 2 or not retryable:
                raise failure("call_api", reason, RuntimeError) from None
            # Only fixed diagnostics are logged; never include raw exception/provider data.
            retry_model = "same_model"
            if timed_out and fallback_model is not None:
                payload = json.loads(body)
                payload["model"] = fallback_model
                request = urllib.request.Request(
                    URL, data=json.dumps(payload).encode(), headers=dict(request.header_items()),
                )
                retry_model = "fallback_model"
            logger.info("stage=call_api attempt=1 retry=%s reason=%s", retry_model, reason)
            time.sleep(random.uniform(0.5, 1.5) if retry_delay is None else retry_delay)

    try:
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except ValueError:
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
    """Validate each envelope container before consuming the model's content."""
    if not isinstance(data, dict) or data.get("error") is not None:
        raise failure(
            "call_api", "AI provider returned an invalid response envelope.", RuntimeError,
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
