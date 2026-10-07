# Offline tests for ai_manager.
# These test the parts that do NOT need the internet: building the prompt,
# reading the AI's JSON reply, and checking it has the right shape.
# We never call the real Groq API here.

import json
import urllib.error
from http.client import IncompleteRead
from unittest.mock import MagicMock, Mock

import ai_manager
import pytest


def test_build_prompt_includes_the_message():
    prompt = ai_manager.build_prompt({"message": "click here to win"})
    assert "click here to win" in prompt
    # it should also ask for JSON with our three keys
    assert "credential_request" in prompt
    assert "suspicious" in prompt
    assert "insufficient_context" in prompt


def test_parse_response_plain_json():
    raw = '{"credential_request": true, "suspicious": false, "insufficient_context": false}'
    data = ai_manager.parse_response(raw)
    assert data["credential_request"] is True
    assert data["suspicious"] is False


def test_parse_response_strips_code_fence():
    # models sometimes wrap the JSON in ```json ... ```
    inner = '{"credential_request": false, "suspicious": true, "insufficient_context": false}'
    raw = "```json\n" + inner + "\n```"
    data = ai_manager.parse_response(raw)
    assert data["suspicious"] is True


def test_validate_response_accepts_good_data():
    good = {"credential_request": True, "suspicious": False, "insufficient_context": False}
    # should return the same dict without raising
    assert ai_manager.validate_response(good) == good


def test_validate_response_rejects_missing_key():
    bad = {"credential_request": True, "suspicious": False}  # no insufficient_context
    with pytest.raises(ValueError):
        ai_manager.validate_response(bad)


def test_validate_response_rejects_wrong_type():
    bad = {"credential_request": "yes", "suspicious": False, "insufficient_context": False}
    with pytest.raises(ValueError):
        ai_manager.validate_response(bad)


@pytest.mark.parametrize("raw", [None, 1, {}, [], b"{}"])
def test_parse_response_rejects_non_text(raw):
    with pytest.raises(ValueError):
        ai_manager.parse_response(raw)


@pytest.mark.parametrize("data", [None, True, 1, "text", [], list(ai_manager.REQUIRED_KEYS)])
def test_response_rejects_non_object_roots(data):
    # Both public boundaries must reject roots that cannot hold named findings.
    with pytest.raises(ValueError):
        ai_manager.parse_response(json.dumps(data))
    with pytest.raises(ValueError):
        ai_manager.validate_response(data)


@pytest.mark.parametrize("fence", ["```", "```json"])
def test_parse_response_accepts_complete_fences(fence):
    expected = {"credential_request": False, "suspicious": True, "insufficient_context": True}
    raw = " \n" + fence + "\n" + json.dumps(expected) + "\n```\n "
    assert ai_manager.validate_response(ai_manager.parse_response(raw)) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "not JSON", '{"suspicious": true',
    '```json\n{}', '```\n{}', '{}\n```',
    '````json\n{}\n````', '```python\n{}\n```',
    'Here is the result: {}', '{} {}',
])
def test_parse_response_rejects_malformed_json_and_wrappers(raw):
    with pytest.raises(ValueError):
        ai_manager.parse_response(raw)


def test_parse_response_rejects_duplicate_fields():
    # JSON's default last-value-wins behaviour could hide a conflicting finding.
    raw = ('{"credential_request": true, "suspicious": true, '
           '"suspicious": false, "insufficient_context": false}')
    with pytest.raises(ValueError):
        ai_manager.parse_response(raw)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parse_response_rejects_non_json_constants(constant):
    with pytest.raises(ValueError):
        ai_manager.parse_response('{"suspicious": ' + constant + '}')


@pytest.mark.parametrize("key", ai_manager.REQUIRED_KEYS)
@pytest.mark.parametrize("value", [0, 1, "true", None, []])
def test_validate_response_never_coerces_findings(key, value):
    data = {"credential_request": False, "suspicious": False, "insufficient_context": False}
    data[key] = value
    with pytest.raises(ValueError):
        ai_manager.validate_response(data)


def test_validate_response_rejects_extra_fields():
    data = {"credential_request": False, "suspicious": False, "insufficient_context": False,
            "priority": "safe"}
    with pytest.raises(ValueError):
        ai_manager.validate_response(data)


def test_validate_response_preserves_findings_without_applying_business_rules():
    data = {"credential_request": True, "suspicious": True, "insufficient_context": True}
    original = data.copy()
    assert ai_manager.validate_response(data) is data
    assert data == original


@pytest.fixture
def provider_transport(monkeypatch):
    """Replace only HTTP transport; keep real API request and response handling."""
    monkeypatch.setenv("GROQ_API_KEY", "fictional-test-key")
    transport = MagicMock()
    monkeypatch.setattr(ai_manager.urllib.request, "urlopen", transport)
    return transport


def test_call_api_returns_completed_content(provider_transport):
    content = '{"credential_request": true, "suspicious": true, "insufficient_context": false}'
    envelope = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    provider_transport.return_value.__enter__.return_value.read.return_value = (
        json.dumps(envelope).encode()
    )

    assert ai_manager.call_api("Fictional phishing assessment") == content
    provider_transport.assert_called_once()
    request = provider_transport.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert body["messages"] == [{"role": "user", "content": "Fictional phishing assessment"}]
    assert body["response_format"] == {"type": "json_object"}
    assert request.get_header("Authorization") == "Bearer fictional-test-key"
    assert provider_transport.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("envelope", [
    None, [], "provider text", 1, {},
    {"choices": None}, {"choices": {}}, {"choices": []}, {"choices": [None]},
    {"choices": [{}]},
    {"choices": [{"finish_reason": "stop", "message": None}]},
    {"choices": [{"finish_reason": "stop", "message": []}]},
    {"choices": [{"finish_reason": "stop", "message": {}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": 1}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": "  "}}]},
    {"error": {"message": "fictional-sensitive-marker"}, "choices": [
        {"finish_reason": "stop", "message": {"content": "{}"}},
    ]},
])
def test_call_api_rejects_malformed_envelopes(provider_transport, envelope):
    provider_transport.return_value.__enter__.return_value.read.return_value = (
        json.dumps(envelope).encode()
    )
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


@pytest.mark.parametrize("reason", [None, "length", "content_filter", "tool_calls"])
def test_call_api_rejects_incomplete_completions(provider_transport, reason):
    # Even schema-valid JSON must not make a truncated/refused completion successful.
    content = '{"credential_request": false, "suspicious": false, "insufficient_context": false}'
    envelope = {"choices": [{"finish_reason": reason, "message": {"content": content}}]}
    provider_transport.return_value.__enter__.return_value.read.return_value = (
        json.dumps(envelope).encode()
    )
    with pytest.raises(RuntimeError):
        ai_manager.call_api("Fictional phishing assessment")
    provider_transport.assert_called_once()


def test_call_api_rejects_refusal_with_content(provider_transport):
    envelope = {"choices": [{"finish_reason": "stop", "message": {
        "content": "{}", "refusal": "fictional-sensitive-marker",
    }}]}
    provider_transport.return_value.__enter__.return_value.read.return_value = (
        json.dumps(envelope).encode()
    )
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


@pytest.mark.parametrize("raw", [
    b"not JSON: fictional-sensitive-marker", b"\xff",
    b'{"choices": [], "choices": []}', b'{"choices": NaN}',
])
def test_call_api_rejects_invalid_provider_json(provider_transport, raw):
    provider_transport.return_value.__enter__.return_value.read.return_value = raw
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


@pytest.mark.parametrize("code", [401, 429, 503])
def test_call_api_reports_http_failure_without_retry(provider_transport, code):
    provider_transport.side_effect = urllib.error.HTTPError(
        "https://example.test/fictional-sensitive-marker", code,
        "fictional-sensitive-marker", {}, None,
    )
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert str(code) in str(failure.value)
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


@pytest.mark.parametrize("error", [
    TimeoutError("fictional-sensitive-marker"),
    urllib.error.URLError("fictional-sensitive-marker"),
])
def test_call_api_sanitises_connection_errors(provider_transport, error):
    provider_transport.side_effect = error
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


@pytest.mark.parametrize("error", [
    OSError("fictional-sensitive-marker"),
    IncompleteRead(b"fictional-sensitive-marker", 100),
])
def test_call_api_handles_failed_response_reads(provider_transport, error):
    provider_transport.return_value.__enter__.return_value.read.side_effect = error
    with pytest.raises(RuntimeError) as failure:
        ai_manager.call_api("Fictional phishing assessment")
    assert "fictional-sensitive-marker" not in str(failure.value)
    provider_transport.assert_called_once()


def test_call_api_requires_key_before_http(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    transport = Mock()
    monkeypatch.setattr(ai_manager.urllib.request, "urlopen", transport)
    with pytest.raises(RuntimeError):
        ai_manager.call_api("Fictional phishing assessment")
    transport.assert_not_called()
