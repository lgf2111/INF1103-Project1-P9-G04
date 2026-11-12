# Offline tests for logic_manager.
# Uses fake AI answers (no real API), so it runs anywhere, including Docker.
# Run with:  pytest

from copy import deepcopy
from dataclasses import FrozenInstanceError

import logic_manager
import pytest
from logic_core import LogicManager, RuleOutcome, RuleTrace
from logic_core.rule_engine import PriorityRuleEngine
from logic_core.rules import (
    CredentialRequestRule,
    DefaultRule,
    DisclosureRule,
    InsufficientContextRule,
    ReportedInteractionRule,
    SuspiciousCredentialRule,
    SuspiciousInteractionRule,
    SuspiciousRule,
)


# Response-priority rules use fictional, already validated AI findings.
def _assessment_record(**changes):
    record = {
        "channel": "email",
        "sender": "fictional@example.test",
        "message": "Fictional message",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
        "ai": {
            "credential_request": False,
            "suspicious": False,
            "insufficient_context": False,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        },
    }
    findings = changes.pop("findings", {})
    record["ai"].update(findings)
    record.update(changes)
    return record


@pytest.mark.parametrize(
    "changes, expected_score, expected_priority",
    [
        pytest.param({}, 10, "LOW", id="routine-message"),
        pytest.param(
            {"findings": {"credential_request": True}},
            40,
            "MEDIUM",
            id="credential-request-alone",
        ),
        pytest.param(
            {"findings": {"insufficient_context": True}}, 20, "LOW", id="insufficient-context"
        ),
        pytest.param({"findings": {"suspicious": True}}, 45, "MEDIUM", id="suspicious"),
        pytest.param(
            {"findings": {"suspicious": True, "credential_request": True}},
            60,
            "MEDIUM",
            id="two-ai-field-rule",
        ),
        pytest.param(
            {"findings": {"suspicious": True}, "clicked": True}, 80, "HIGH", id="suspicious-clicked"
        ),
        pytest.param(
            {"findings": {"suspicious": True}, "downloaded": True},
            80,
            "HIGH",
            id="suspicious-downloaded",
        ),
        pytest.param(
            {"submitted_category": "password"},
            90,
            "HIGH",
            id="password-disclosure-with-negative-ai",
        ),
        pytest.param(
            {"submitted_category": "otp"}, 90, "HIGH", id="otp-disclosure-with-negative-ai"
        ),
        pytest.param(
            {
                "submitted_category": "otp",
                "clicked": True,
                "downloaded": True,
                "findings": {
                    "suspicious": True,
                    "credential_request": True,
                    "insufficient_context": True,
                },
            },
            90,
            "HIGH",
            id="disclosure-wins-all-overlapping-rules",
        ),
        pytest.param(
            {
                "clicked": True,
                "findings": {
                    "suspicious": True,
                    "credential_request": True,
                    "insufficient_context": True,
                },
            },
            80,
            "HIGH",
            id="interaction-wins-request-and-uncertainty",
        ),
        pytest.param(
            {
                "findings": {
                    "suspicious": True,
                    "credential_request": True,
                    "insufficient_context": True,
                }
            },
            60,
            "MEDIUM",
            id="two-fields-win-uncertainty",
        ),
        pytest.param(
            {"findings": {"suspicious": True, "insufficient_context": True}},
            45,
            "MEDIUM",
            id="suspicion-wins-uncertainty",
        ),
        pytest.param(
            {"clicked": True, "downloaded": True},
            35,
            "MEDIUM",
            id="interaction-alone-requires-caution",
        ),
    ],
)
def test_response_priority_scenarios(changes, expected_score, expected_priority):
    record = _assessment_record(**deepcopy(changes))
    original = deepcopy(record)

    assert logic_manager.score(record) == expected_score
    assert type(logic_manager.score(record)) is int
    assert logic_manager.route(record) == {
        "score": expected_score,
        "priority": expected_priority,
    }
    assert record == original


def test_class_based_manager_evaluates_ai_enriched_record():
    manager = LogicManager()
    record = _assessment_record(
        findings={"suspicious": True, "credential_request": True}
    )
    original = deepcopy(record)

    assert manager.score(record) == 60
    assert manager.route(record) == {"score": 60, "priority": "MEDIUM"}
    result = manager.evaluate(record)

    assert result["score"] == 60
    assert result["priority"] == "MEDIUM"
    assert result["matched_rule"] == "SuspiciousCredentialRule"
    assert [step["rule_name"] for step in result["trace"]] == [
        "DisclosureRule",
        "SuspiciousInteractionRule",
        "SuspiciousCredentialRule",
    ]
    assert [step["matched"] for step in result["trace"]] == [False, False, True]
    assert result["trace"][-1]["score"] == 60
    assert result["reasons"] and result["checklist"]
    assert record == original


def test_rule_engine_uses_injected_rules_in_order():
    record = _assessment_record(
        findings={"suspicious": True, "credential_request": True}
    )
    manager = LogicManager(
        rule_engine=PriorityRuleEngine((SuspiciousRule(), DefaultRule()))
    )

    # The shared rule contract lets the engine use different concrete rules
    # without adding rule-specific branches to the engine.
    assert manager.score(record) == 45


@pytest.mark.parametrize(
    "rule_type, changes, expected_score",
    [
        (DisclosureRule, {"submitted_category": "password"}, 90),
        (
            SuspiciousInteractionRule,
            {"findings": {"suspicious": True}, "clicked": True},
            80,
        ),
        (
            SuspiciousCredentialRule,
            {"findings": {"suspicious": True, "credential_request": True}},
            60,
        ),
        (SuspiciousRule, {"findings": {"suspicious": True}}, 45),
        (CredentialRequestRule, {"findings": {"credential_request": True}}, 40),
        (ReportedInteractionRule, {"downloaded": True}, 35),
        (InsufficientContextRule, {"findings": {"insufficient_context": True}}, 20),
        (DefaultRule, {}, 10),
    ],
)
def test_each_priority_rule_returns_an_immutable_outcome(
    rule_type, changes, expected_score
):
    outcome = rule_type().evaluate(_assessment_record(**deepcopy(changes)))

    assert outcome == RuleOutcome(rule_name=rule_type.__name__, score=expected_score)
    with pytest.raises(FrozenInstanceError):
        outcome.score = 0


def test_logic_manager_exposes_rule_outcome_without_changing_score_api():
    record = _assessment_record(findings={"suspicious": True})
    manager = LogicManager()

    outcome = manager.rule_outcome(record)
    assert outcome.rule_name == "SuspiciousRule"
    assert outcome.score == 45
    assert outcome.trace == (
        RuleTrace("DisclosureRule", False),
        RuleTrace("SuspiciousInteractionRule", False),
        RuleTrace("SuspiciousCredentialRule", False),
        RuleTrace("SuspiciousRule", True, 45),
    )
    assert manager.score(record) == 45


def test_class_based_manager_rejects_invalid_ai_findings():
    manager = LogicManager()
    record = _assessment_record(findings={"suspicious": "false"})

    with pytest.raises(ValueError, match="AI finding must be true or false"):
        manager.evaluate(record)


def test_contact_link_and_file_presence_do_not_increase_response_priority():
    record = _assessment_record(
        has_link=True,
        link="https://fictional.example.test",
        has_file=True,
        file_name="fictional.pdf",
        sender=None,
    )
    record["ai"]["details"] = {
        "emails": ["fictional@example.test"],
        "phone_numbers": ["12345678"],
        "ip_addresses": ["192.0.2.10"],
    }
    assert logic_manager.score(record) == 10
    assert logic_manager.route(record) == {"score": 10, "priority": "LOW"}


@pytest.mark.parametrize(
    "value, priority",
    [
        (0, "LOW"),
        (34, "LOW"),
        (35, "MEDIUM"),
        (69, "MEDIUM"),
        (70, "HIGH"),
        (100, "HIGH"),
    ],
)
@pytest.mark.parametrize("operation", ["route", "evaluate"])
def test_priority_thresholds(monkeypatch, value, priority, operation):
    """Check both public entry points use the same thresholds and score once."""
    # Isolate routing thresholds, including scores not generated by today's rule table.
    record = _assessment_record()
    calls = []

    def fixed_score(received):
        """Record the scoring call and supply the requested boundary value."""
        calls.append(received)
        return value

    if operation == "route":
        monkeypatch.setattr(logic_manager, "score", fixed_score)
    else:
        fixed_outcome = RuleOutcome("BoundaryRule", value)

        def fixed_rule_outcome(received):
            calls.append(received)
            return fixed_outcome

        monkeypatch.setattr(
            logic_manager._DEFAULT_MANAGER, "rule_outcome", fixed_rule_outcome
        )
    result = getattr(logic_manager, operation)(record)
    assert result["score"] == value
    assert result["priority"] == priority
    assert calls == [record]


def test_evaluate_scores_once(monkeypatch):
    """Check real scoring and validation run once without changing the record."""
    record = _assessment_record(submitted_category="password")
    original = deepcopy(record)
    original_outcome = logic_manager._DEFAULT_MANAGER.rule_outcome
    calls = []

    def track_outcome(received):
        """Count rule evaluation while preserving validation and rules."""
        calls.append(received)
        return original_outcome(received)

    # Wrap real rule evaluation so this regression exercises validation and rules.
    monkeypatch.setattr(logic_manager._DEFAULT_MANAGER, "rule_outcome", track_outcome)
    result = logic_manager.evaluate(record)

    assert len(calls) == 1
    assert calls[0] is record
    assert result["score"] == 90
    assert result["priority"] == "HIGH"
    assert record == original


def test_evaluate_uses_one_rule_outcome(monkeypatch):
    """Check evaluation uses one rule outcome for routing, trace, and guidance."""
    record = _assessment_record()
    original = deepcopy(record)
    calls = []
    expected_trace = (RuleTrace("SyntheticRule", True, 80),)

    def fixed_outcome(received):
        """Return an outcome distinct from the record's default rule."""
        calls.append(received)
        return RuleOutcome("SyntheticRule", 80, expected_trace)

    monkeypatch.setattr(logic_manager._DEFAULT_MANAGER, "rule_outcome", fixed_outcome)
    result = logic_manager.evaluate(record)

    assert len(calls) == 1
    assert calls[0] is record
    assert result["score"] == 80
    assert result["priority"] == "HIGH"
    assert result["matched_rule"] == "SyntheticRule"
    assert result["trace"] == tuple(step.as_dict() for step in expected_trace)
    assert record == original


@pytest.mark.parametrize(
    "changes",
    [
        {"ai": None},
        {"ai": {}},
        {"ai": {"credential_request": True, "suspicious": True}},
        {"findings": {"suspicious": "false"}},
        {"findings": {"credential_request": 1}},
        {"findings": {"insufficient_context": []}},
        {"clicked": "yes"},
        {"downloaded": 1},
        {"submitted_category": "payment"},
    ],
)
@pytest.mark.parametrize("operation", ["score", "route", "evaluate"])
def test_response_priority_rejects_invalid_inputs(changes, operation):
    record = _assessment_record(**deepcopy(changes))
    original = deepcopy(record)
    with pytest.raises(ValueError):
        getattr(logic_manager, operation)(record)
    assert record == original


@pytest.mark.parametrize("operation", ["score", "route", "evaluate"])
def test_disclosure_still_requires_an_ai_assessment(operation):
    record = _assessment_record(submitted_category="password")
    del record["ai"]
    with pytest.raises(ValueError):
        getattr(logic_manager, operation)(record)


@pytest.mark.parametrize(
    "changes, expected_score, expected_priority",
    [
        ({}, 10, "LOW"),
        ({"findings": {"insufficient_context": True}}, 20, "LOW"),
        ({"findings": {"credential_request": True}}, 40, "MEDIUM"),
        ({"findings": {"suspicious": True}}, 45, "MEDIUM"),
        ({"findings": {"suspicious": True, "credential_request": True}}, 60, "MEDIUM"),
        ({"clicked": True, "findings": {"suspicious": True}}, 80, "HIGH"),
        ({"submitted_category": "password"}, 90, "HIGH"),
        ({"submitted_category": "otp"}, 90, "HIGH"),
    ],
)
def test_evaluate_uses_ai_response_priority_without_mutation(
    changes,
    expected_score,
    expected_priority,
):
    record = _assessment_record(**deepcopy(changes))
    original = deepcopy(record)
    result = logic_manager.evaluate(record)
    assert result["score"] == expected_score
    assert result["priority"] == expected_priority
    assert result["reasons"] and all(isinstance(r, str) for r in result["reasons"])
    assert result["checklist"] and all(isinstance(r, str) for r in result["checklist"])
    assert record == original


@pytest.mark.parametrize("category, guidance", [("password", "password"), ("otp", "one-time code")])
def test_evaluate_addresses_disclosure_despite_negative_ai(category, guidance):
    result = logic_manager.evaluate(_assessment_record(submitted_category=category))
    assert result["priority"] == "HIGH"
    assert any(guidance in reason.lower() for reason in result["reasons"])
    assert any(guidance in step.lower() for step in result["checklist"])


def test_evaluate_uncertainty_and_low_priority_do_not_claim_safety():
    for findings in ({}, {"insufficient_context": True}):
        result = logic_manager.evaluate(_assessment_record(findings=findings))
        text = " ".join(result["reasons"] + result["checklist"]).lower()
        assert "safe" not in text
        assert any("verify" in step.lower() for step in result["checklist"])
        if findings:
            assert "insufficient context" in text


@pytest.mark.parametrize("action, guidance", [("clicked", "link"), ("downloaded", "file")])
def test_evaluate_guidance_matches_reported_interaction(action, guidance):
    record = _assessment_record(**{action: True}, findings={"suspicious": True})
    result = logic_manager.evaluate(record)
    assert any(guidance in step.lower() for step in result["checklist"])
    assert not any(
        "change" in step.lower() and "password" in step.lower() for step in result["checklist"]
    )
