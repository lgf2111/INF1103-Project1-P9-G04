# Offline tests for ai_manager.
# These test the parts that do NOT need the internet: building the prompt,
# reading the AI's JSON reply, and checking it has the right shape.
# We never call the real Groq API here.

import json

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
