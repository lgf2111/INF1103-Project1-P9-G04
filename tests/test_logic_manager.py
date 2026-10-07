# Offline tests for logic_manager.
# Uses fake AI answers (no real API), so it runs anywhere, including Docker.
# Run with:  pytest

from copy import deepcopy

import logic_manager
import pytest


@pytest.mark.parametrize(
    "details",
    [
        {"emails": [], "phone_numbers": [], "ip_addresses": []},
        {"emails": ["demo123@example.test"], "phone_numbers": [], "ip_addresses": []},
        {"emails": [], "phone_numbers": ["12345678"], "ip_addresses": []},
        {"emails": [], "phone_numbers": [], "ip_addresses": ["2001:DB8::10", "192.0.2.10"]},
        {
            "emails": ["b2@example.test", "a1@example.test", "b2@example.test"],
            "phone_numbers": ["87654321", "12345678", "87654321"],
            "ip_addresses": ["2001:DB8::10", "192.0.2.10", "2001:DB8::10"],
        },
    ],
    ids=["empty", "email-only", "phone-only", "ip-only", "all-with-repeats"],
)
def test_hold_details(details):
    """Preserve the dictionary, lists, and values through the Logic Manager."""
    # Snapshot values and list references to detect mutation or replacement.
    original_values = deepcopy(details)
    original_lists = details.copy()

    returned = logic_manager.hold_details(details)

    # The handoff must preserve identity as well as order and repeated values.
    assert returned is details
    assert returned == original_values
    for key, original_list in original_lists.items():
        assert returned[key] is original_list


# Response-priority rules use fictional, already validated AI findings.
def _assessment_record(**changes):
    record = {
        "channel": "email", "sender": "fictional@example.test",
        "message": "Fictional message", "has_link": False, "link": None,
        "has_file": False, "file_name": None, "clicked": False, "downloaded": False,
        "submitted_category": None,
        "ai": {"credential_request": False, "suspicious": False,
               "insufficient_context": False,
               "details": {"emails": [], "phone_numbers": [], "ip_addresses": []}},
    }
    findings = changes.pop("findings", {})
    record["ai"].update(findings)
    record.update(changes)
    return record


@pytest.mark.parametrize("changes, expected_score, expected_priority", [
    pytest.param({}, 10, "LOW", id="routine-message"),
    pytest.param({"findings": {"credential_request": True}}, 10, "LOW",
                 id="credential-request-alone"),
    pytest.param({"findings": {"insufficient_context": True}}, 35, "MEDIUM",
                 id="insufficient-context"),
    pytest.param({"findings": {"suspicious": True}}, 45, "MEDIUM", id="suspicious"),
    pytest.param({"findings": {"suspicious": True, "credential_request": True}},
                 60, "MEDIUM", id="two-ai-field-rule"),
    pytest.param({"findings": {"suspicious": True}, "clicked": True},
                 80, "HIGH", id="suspicious-clicked"),
    pytest.param({"findings": {"suspicious": True}, "downloaded": True},
                 80, "HIGH", id="suspicious-downloaded"),
    pytest.param({"submitted_category": "password"}, 90, "HIGH",
                 id="password-disclosure-with-negative-ai"),
    pytest.param({"submitted_category": "otp"}, 90, "HIGH",
                 id="otp-disclosure-with-negative-ai"),
    pytest.param({"submitted_category": "otp", "clicked": True, "downloaded": True,
                  "findings": {"suspicious": True, "credential_request": True,
                               "insufficient_context": True}},
                 90, "HIGH", id="disclosure-wins-all-overlapping-rules"),
    pytest.param({"clicked": True,
                  "findings": {"suspicious": True, "credential_request": True,
                               "insufficient_context": True}},
                 80, "HIGH", id="interaction-wins-request-and-uncertainty"),
    pytest.param({"findings": {"suspicious": True, "credential_request": True,
                               "insufficient_context": True}},
                 60, "MEDIUM", id="two-fields-win-uncertainty"),
    pytest.param({"findings": {"suspicious": True, "insufficient_context": True}},
                 45, "MEDIUM", id="suspicion-wins-uncertainty"),
    pytest.param({"clicked": True, "downloaded": True}, 10, "LOW",
                 id="interaction-alone-does-not-establish-suspicion"),
])
def test_response_priority_scenarios(changes, expected_score, expected_priority):
    record = _assessment_record(**deepcopy(changes))
    original = deepcopy(record)

    assert logic_manager.score(record) == expected_score
    assert type(logic_manager.score(record)) is int
    assert logic_manager.route(record) == expected_priority
    assert record == original


def test_contact_link_and_file_presence_do_not_increase_response_priority():
    record = _assessment_record(has_link=True, link="https://fictional.example.test",
                                has_file=True, file_name="fictional.pdf", sender=None)
    record["ai"]["details"] = {
        "emails": ["fictional@example.test"], "phone_numbers": ["12345678"],
        "ip_addresses": ["192.0.2.10"],
    }
    assert logic_manager.score(record) == 10
    assert logic_manager.route(record) == "LOW"


@pytest.mark.parametrize("value, priority", [
    (0, "LOW"), (34, "LOW"), (35, "MEDIUM"), (69, "MEDIUM"),
    (70, "HIGH"), (100, "HIGH"),
])
def test_route_thresholds_use_the_logic_score(monkeypatch, value, priority):
    # Isolate routing thresholds, including scores not generated by today's rule table.
    record = _assessment_record()
    calls = []

    def fixed_score(received):
        calls.append(received)
        return value

    monkeypatch.setattr(logic_manager, "score", fixed_score)
    assert logic_manager.route(record) == priority
    assert calls == [record]


@pytest.mark.parametrize("changes", [
    {"ai": None}, {"ai": {}},
    {"ai": {"credential_request": True, "suspicious": True}},
    {"findings": {"suspicious": "false"}},
    {"findings": {"credential_request": 1}},
    {"findings": {"insufficient_context": []}},
    {"clicked": "yes"}, {"downloaded": 1}, {"submitted_category": "payment"},
])
@pytest.mark.parametrize("operation", ["score", "route"])
def test_response_priority_rejects_invalid_inputs(changes, operation):
    record = _assessment_record(**deepcopy(changes))
    original = deepcopy(record)
    with pytest.raises(ValueError):
        getattr(logic_manager, operation)(record)
    assert record == original


@pytest.mark.parametrize("operation", ["score", "route"])
def test_disclosure_still_requires_an_ai_assessment(operation):
    record = _assessment_record(submitted_category="password")
    del record["ai"]
    with pytest.raises(ValueError):
        getattr(logic_manager, operation)(record)
