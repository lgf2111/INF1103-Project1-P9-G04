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
import urllib.error
import urllib.request

from .errors import failure
from .parsing import reject_constant, unique_object

# Groq's API is OpenAI-style. Change the model with the GROQ_MODEL env var.
# (Run the /models endpoint or check the Groq console to see what your key can use.)
DEFAULT_MODEL = "openai/gpt-oss-20b"
URL = "https://api.groq.com/openai/v1/chat/completions"


def call_api(prompt: str) -> str:
    """Send one request and return content from a completed provider response.

    Require nonblank prompt text, otherwise raise ValueError before configuration/HTTP.
    Preserve valid prompt text exactly as supplied.
    Raise RuntimeError for missing credentials, HTTP/connection/read failures,
    invalid provider JSON, malformed envelopes or incomplete/refused answers.
    Error messages exclude provider bodies and underlying exception details.
    Read GROQ_MODEL at request time, after the caller has loaded its environment.
    An unset model uses DEFAULT_MODEL; an explicitly blank setting is rejected.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise failure("call_api", "AI prompt must be nonblank text.", ValueError)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise failure("call_api", "Set the GROQ_API_KEY environment variable first.", RuntimeError)

    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    if not model.strip():
        raise failure("call_api", "GROQ_MODEL must not be blank.", RuntimeError)

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
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise failure(
            "call_api", f"AI provider returned HTTP {error.code}.", RuntimeError,
        ) from None
    except TimeoutError:
        raise failure("call_api", "The AI request timed out.", RuntimeError) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise failure("call_api", "Could not complete the AI request.", RuntimeError) from None

    try:
        data = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except ValueError:
        raise failure("call_api", "AI provider returned invalid JSON.", RuntimeError) from None
    return _completed_content(data)


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
