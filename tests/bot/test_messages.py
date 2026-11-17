"""Exposure keyboard payloads reflect explicit answers without changing state."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from telegram import InlineKeyboardMarkup

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot import messages
from phishreport.bot.exposure import ExposureSession
from phishreport.logic import LogicManager
from phishreport.model import AssessmentResult, RuleTrace


@pytest.fixture
def session():
    return ExposureSession(
        {"message": "private message", "sender": "private sender"},
        AssessmentSnapshot(
            findings={"private": ["AI findings"]},
            result={"score": 60, "reasons": ["private reason"]},
        ),
        chat_id=123456, user_id=234567, message_id=345678,
    )


def test_saved_card_keyboard_has_exact_buttons_and_private_callback_payloads(session):
    session.saved = True

    keyboard = messages.MessageFactory.build_exposure_keyboard(session)

    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Clicked link", "Shared a password/OTP"],
        ["Nothing happened"],
    ]
    assert messages.EXPOSURE_CALLBACK_PREFIX == "exposure"
    actions = [["clicked", "password"], ["nothing"]]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        [f"exposure:{session.token}:{action}" for action in row] for row in actions
    ]
    for row in keyboard.to_dict()["inline_keyboard"]:
        for button in row:
            assert set(button) == {"text", "callback_data"}
            assert len(button["callback_data"].encode("utf-8")) < 64
            assert button["callback_data"].split(":")[1] == session.token


@pytest.mark.parametrize(
    ("clicked", "category", "answered", "labels"),
    [
        (True, None, False, [["Shared a password/OTP", "Nothing else"]]),
        (None, "password", True, None),
        (True, "password", True, None),
    ],
)
def test_keyboard_offers_only_answers_that_can_still_change_the_result(
    session, clicked, category, answered, labels,
):
    session.saved = True
    session.exposure.update(
        clicked=clicked, submitted_category=category, disclosure_answered=answered,
    )

    keyboard = messages.MessageFactory.build_exposure_keyboard(session)

    if labels is None:
        assert keyboard is None
        return
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == labels
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        [f"exposure:{session.token}:password", f"exposure:{session.token}:nothing"],
    ]


@pytest.mark.parametrize("saved,dismissed", [
    (False, False), (True, True), (False, True),
])
def test_unsaved_or_dismissed_session_has_no_keyboard(session, saved, dismissed):
    session.saved = saved
    session.dismissed = dismissed

    assert messages.MessageFactory.build_exposure_keyboard(session) is None


def test_keyboard_is_read_only_without_mutation_scoring_or_time_checks(session, monkeypatch):
    session.saved = True
    session.expires_at = 0
    before = dict(session.__dict__)
    values = {key: deepcopy(value) for key, value in before.items() if key != "lock"}
    for name in ("assess", "assess_with_findings", "rescore", "build_exposure_report"):
        monkeypatch.setattr(AssessmentService, name, Mock(side_effect=AssertionError(name)))
    monkeypatch.setattr("phishreport.bot.exposure.time.monotonic",
                        Mock(side_effect=AssertionError("clock access")))

    first = messages.MessageFactory.build_exposure_keyboard(session)
    second = messages.MessageFactory.build_exposure_keyboard(session)

    assert first == second
    assert first is not second
    assert all(session.__dict__[key] is value for key, value in before.items())
    assert {key: value for key, value in session.__dict__.items() if key != "lock"} == values


def test_confirmation_card_quotes_the_exact_text_and_warning():
    assert messages.MessageFactory.build_confirmation_card("Verify your password now") == (
        'Check this message?\n\n"Verify your password now"\n\n'
        "This text is sent to the AI provider for analysis."
    )
    assert messages.CONFIRMATION_PROMPT == "Check this message?"
    assert (
        messages.CONFIRMATION_WARNING
        == "This text is sent to the AI provider for analysis."
    )


def test_confirmation_copy_is_exact():
    assert messages.CONFIRMATION_YES == "Yes, check it"
    assert messages.CONFIRMATION_CANCEL == "Cancel"
    assert messages.CONFIRMATION_CANCELLED == "Cancelled. Nothing was sent or saved."
    assert (
        messages.CONFIRMATION_EXPIRED
        == "This confirmation expired. Paste the message again."
    )


@pytest.mark.parametrize("length", [0, 1, 399, 400])
def test_confirmation_preview_keeps_text_at_or_below_the_limit(length):
    text = "Z" * length

    assert messages.MessageFactory.confirmation_preview(text) == text
    assert messages.MessageFactory.build_confirmation_card(text).count("Z") == length


def test_confirmation_preview_truncates_to_400_characters_with_an_ellipsis():
    text = "Z" * 401

    preview = messages.MessageFactory.confirmation_preview(text)

    assert preview == "Z" * 400 + "..."
    assert len(preview) == 403
    card = messages.MessageFactory.build_confirmation_card(text)
    assert f'"{preview}"' in card
    assert "Z" * 401 not in card


def test_confirmation_keyboard_has_exact_yes_and_cancel_payloads():
    token = "A" * 16

    keyboard = messages.MessageFactory.build_confirmation_keyboard(token)

    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Yes, check it", "Cancel"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        [f"exposure:{token}:confirm", f"exposure:{token}:cancel"],
    ]
    for row in keyboard.to_dict()["inline_keyboard"]:
        for button in row:
            assert set(button) == {"text", "callback_data"}
            assert len(button["callback_data"].encode("utf-8")) < 64


@pytest.fixture
def assessed_session():
    service = AssessmentService(Mock(), LogicManager())
    record = messages.ChatRecordBuilder().build("Verify your account password now.")
    findings = {"suspicious": True, "credential_request": True,
                "insufficient_context": False}
    state = ExposureSession(
        record, AssessmentSnapshot(findings, service.rescore(record, findings)),
        chat_id=123456, user_id=234567, message_id=345678,
    )
    state.saved = True
    return state, service


def test_formatter_short_legacy_output_stays_identical():
    result = {"score": 60, "priority": "MEDIUM", "reasons": ["Urgency"],
              "checklist": ["Verify independently"]}

    assert messages.ResultFormatter().format(result) == (
        "=== Assessment ===\nPriority: Medium\nRule-based score: 60\n\nReasons:"
        "\n - Urgency\n\nRecommended actions:\n1. Verify independently\n\n"
        "A low priority result does not guarantee that a message is safe."
    )


def test_card_keeps_priority_score_rule_reasons_and_actions_only(assessed_session):
    state, _ = assessed_session

    text = messages.ResultFormatter().format({}, session=state)

    assert "Priority: Medium" in text
    assert "Rule-based score: 60" in text
    assert "Matched rule: SuspiciousCredentialRule" in text
    assert "Reasons:" in text and "- The AI identified" in text
    assert "Recommended actions:" in text and "1. " in text
    assert "Rule evaluation trace" not in text
    assert "Provisional" not in text
    assert "Did you" not in text
    assert "Exposure unconfirmed" not in text
    assert "Report not saved" not in text and "saved locally" not in text.lower()
    assert "expire" not in text.lower() and "30 minutes" not in text
    assert messages.ResultFormatter.FOOTER not in text


def test_card_shows_the_latest_rescored_result(assessed_session):
    state, service = assessed_session

    exposure, result = state.answer("clicked", service)
    state.commit(exposure, result, state.build_report(service, exposure=exposure, result=result))
    text = messages.ResultFormatter().format({}, session=state)

    assert "Priority: High" in text
    assert "Rule-based score: 80" in text
    assert "You reported clicking a link." in text
    assert "Rule-based score: 60" not in text
    assert messages.EXPOSURE_SAVED not in text


def test_card_ends_with_the_saved_line_once_no_answer_remains(assessed_session):
    state, service = assessed_session

    exposure, result = state.answer("password", service)
    state.commit(exposure, result, state.build_report(service, exposure=exposure, result=result))
    text = messages.ResultFormatter().format({}, session=state)

    assert "Rule-based score: 90" in text
    assert text.endswith("\n\n" + messages.EXPOSURE_SAVED)
    assert messages.EXPOSURE_SAVED == "Saved. Nothing more to answer."


def test_formatter_is_read_only_and_never_touches_scoring_or_time(assessed_session, monkeypatch):
    state, _ = assessed_session
    before = dict(state.__dict__)
    values = {key: deepcopy(value) for key, value in before.items() if key != "lock"}
    monkeypatch.setattr(
        messages.MessageFactory, "build_exposure_keyboard", Mock(side_effect=AssertionError)
    )
    monkeypatch.setattr("phishreport.bot.exposure.time.monotonic",
                        Mock(side_effect=AssertionError))
    for name in ("assess", "assess_with_findings", "rescore", "build_exposure_report"):
        monkeypatch.setattr(AssessmentService, name, Mock(side_effect=AssertionError))

    text = messages.ResultFormatter().format({}, session=state)

    assert "Rule-based score: 60" in text
    assert all(state.__dict__[key] is value for key, value in before.items())
    assert {key: value for key, value in state.__dict__.items() if key != "lock"} == values
    for private in (state.token, "123456", "234567", "345678", "AI findings",
                    "private message", "private sender"):
        assert private not in text


@pytest.mark.parametrize("character", ["A", "😀"])
def test_card_bounds_the_reply_in_utf16_without_notices(assessed_session, character):
    state, _ = assessed_session
    state.result = {
        "score": 80, "priority": "HIGH",
        "reasons": [character * 6000], "checklist": ["Act now"],
    }

    text = messages.ResultFormatter().format(state.result, session=state)

    assert len(text.encode("utf-16-le")) // 2 <= 4000
    assert text.encode("utf-16-le").decode("utf-16-le") == text
    assert "..." in text and "Rule-based score: 80" in text
    assert messages.ResultFormatter.FOOTER not in text
    assert "Provisional" not in text and "expire" not in text.lower()


def test_alert_renders_typed_result_with_safe_html_and_ordered_trace():
    result = AssessmentResult(
        score=80, priority="HIGH", matched_rule="Winner<&>",
        trace=(RuleTrace("First<&>", False), RuleTrace("Winner<&>", True, 80)),
        reasons=("<script>" + "x" * 400,),
        checklist=tuple(f"Verify <{number}>" for number in range(6)),
    )

    text = messages.PhishingAlertFormatter().format(
        result, "Sender <x&y>", "Subject <unsafe>", 'https://mail.test/?q="x"&a=1',
    )

    assert "🚨 <b>HIGH risk</b>" in text
    assert "<b>Score:</b> 80/100" in text
    assert "Sender &lt;x&amp;y&gt;" in text and "Subject &lt;unsafe&gt;" in text
    assert "<b>Matched rule:</b> Winner&lt;&amp;&gt;" in text
    assert "• First&lt;&amp;&gt;: not matched\n• Winner&lt;&amp;&gt;: matched (score: 80)" in text
    assert "&lt;script&gt;" + "x" * 289 + "..." in text
    assert "<script>" not in text
    assert "5. Verify &lt;4&gt;" in text and "Verify &lt;5&gt;" not in text
    assert 'href="https://mail.test/?q=&quot;x&quot;&amp;a=1"' in text
    assert text.endswith("<i>Do not click links or reply. A low score never guarantees safety.</i>")


def test_alert_uses_tolerant_projection_for_malformed_fields_without_mutating_input():
    result = {
        "score": True, "priority": ["HIGH"], "matched_rule": {"private": "rule"},
        "trace": [None, {"rule_name": "broken", "matched": "yes"}],
        "reasons": ["Keep <this>", 123, None], "checklist": "not a list",
    }
    before = deepcopy(result)

    text = messages.PhishingAlertFormatter().format(result, None)

    assert "⚠️ <b>Possible phishing</b>" in text
    assert "<b>Score:</b> n/a/100" in text
    assert "Unknown sender" in text
    assert "• Keep &lt;this&gt;" in text and "123" not in text
    assert "Matched rule" not in text and "Rule evaluation trace" not in text
    assert "What to do" not in text and "private" not in text
    assert result == before


@pytest.mark.parametrize("result", [{}, None, []])
def test_alert_missing_assessment_preserves_unknown_score(result):
    text = messages.PhishingAlertFormatter().format(result, None)

    assert "<b>Score:</b> n/a/100" in text
    assert "<b>Possible phishing</b>" in text
    assert "Why it was flagged" not in text and "What to do" not in text


@pytest.mark.parametrize("score", [0, 12.5])
def test_alert_preserves_zero_and_finite_legacy_score(score):
    text = messages.PhishingAlertFormatter().format({"score": score}, None)

    assert f"<b>Score:</b> {score}/100" in text
