"""Exposure keyboard payloads reflect explicit answers without changing state."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from telegram import InlineKeyboardMarkup

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot import messages
from phishreport.bot.exposure import ExposureSession
from phishreport.logic import LogicManager


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


def test_pending_keyboard_has_exact_rows_and_private_callback_payloads(session):
    keyboard = messages.build_exposure_keyboard(session)

    assert isinstance(keyboard, InlineKeyboardMarkup)
    assert [[button.text for button in row] for row in keyboard.inline_keyboard] == [
        ["Clicked link", "Downloaded file"],
        ["Both", "Neither"],
        ["Password", "One-time code"],
        ["Neither password nor code"],
        ["Finish and save", "Skip unanswered"],
    ]
    assert messages.EXPOSURE_CALLBACK_PREFIX == "exposure"
    actions = [
        ["clicked", "downloaded"], ["both", "neither"],
        ["password", "otp"], ["no_disclosure"], ["finish", "skip"],
    ]
    assert [[button.callback_data for button in row] for row in keyboard.inline_keyboard] == [
        [f"exposure:{session.token}:{action}" for action in row] for row in actions
    ]
    for row in keyboard.to_dict()["inline_keyboard"]:
        for button in row:
            assert set(button) == {"text", "callback_data"}
            assert len(button["callback_data"].encode("utf-8")) < 64
            assert button["callback_data"].split(":")[1] == session.token


@pytest.mark.parametrize(
    ("clicked", "downloaded", "interaction"),
    [(True, False, "Clicked link"), (False, True, "Downloaded file"),
     (True, True, "Both"), (False, False, "Neither"), (None, None, None)],
)
@pytest.mark.parametrize(
    ("category", "answered", "disclosure"),
    [("password", True, "Password"), ("otp", True, "One-time code"),
     (None, True, "Neither password nor code"), (None, False, None)],
)
def test_selected_answers_remain_independent(
    session, clicked, downloaded, interaction, category, answered, disclosure
):
    session.exposure.update(
        clicked=clicked, downloaded=downloaded,
        submitted_category=category, disclosure_answered=answered,
    )

    keyboard = messages.build_exposure_keyboard(session)

    selected = {button.text for row in keyboard.inline_keyboard
                for button in row if button.text.startswith("✓ ")}
    assert selected == {f"✓ {label}" for label in (interaction, disclosure) if label}


@pytest.mark.parametrize(
    ("clicked", "downloaded"),
    [(None, False), (False, None), (True, None), (None, True),
     (1, False), (False, 1), (0, True), (True, 0), ("yes", False)],
)
def test_partial_or_nonboolean_interaction_does_not_fabricate_selection(
    session, clicked, downloaded
):
    session.exposure.update(clicked=clicked, downloaded=downloaded)

    keyboard = messages.build_exposure_keyboard(session)

    assert not any(button.text.startswith("✓ ")
                   for row in keyboard.inline_keyboard for button in row)


@pytest.mark.parametrize(
    ("category", "answered"),
    [("password", False), ("otp", False), ("password", 1), (None, 1), ("unknown", True)],
)
def test_unconfirmed_or_unknown_disclosure_is_not_selected(session, category, answered):
    session.exposure.update(submitted_category=category, disclosure_answered=answered)

    keyboard = messages.build_exposure_keyboard(session)

    assert not any(button.text.startswith("✓ ")
                   for row in keyboard.inline_keyboard for button in row)


def test_completed_unsaved_keyboard_only_offers_retry(session):
    session.completed = True

    keyboard = messages.build_exposure_keyboard(session)

    assert keyboard.to_dict() == {"inline_keyboard": [[{
        "text": "Retry saving", "callback_data": f"exposure:{session.token}:retry",
    }]]}


@pytest.mark.parametrize("completed", [False, True])
def test_saved_session_has_no_keyboard(session, completed):
    session.completed = completed
    session.saved = True

    assert messages.build_exposure_keyboard(session) is None


@pytest.mark.parametrize("completed", [False, True])
def test_render_uses_snapshot_only_without_mutation_scoring_or_time_checks(
    session, monkeypatch, completed
):
    session.completed = completed
    session.expires_at = 0
    before = dict(session.__dict__)
    values = {key: deepcopy(value) for key, value in before.items() if key != "lock"}
    for name in ("assess", "assess_with_findings", "rescore", "build_exposure_report"):
        monkeypatch.setattr(AssessmentService, name, Mock(side_effect=AssertionError(name)))
    monkeypatch.setattr("phishreport.bot.exposure.time.monotonic",
                        Mock(side_effect=AssertionError("clock access")))

    first = messages.build_exposure_keyboard(session)
    second = messages.build_exposure_keyboard(session)

    assert first == second
    assert first is not second
    assert all(session.__dict__[key] is value for key, value in before.items())
    assert {key: value for key, value in session.__dict__.items() if key != "lock"} == values


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
    return state, service


def test_formatter_short_legacy_output_stays_identical():
    result = {"score": 60, "priority": "MEDIUM", "reasons": ["Urgency"],
              "checklist": ["Verify independently"]}

    assert messages.ResultFormatter().format(result) == (
        "=== Assessment ===\nPriority: Medium\nRule-based score: 60\n\nReasons:"
        "\n - Urgency\n\nRecommended actions:\n1. Verify independently\n\n"
        "A low priority result does not guarantee that a message is safe."
    )


@pytest.mark.parametrize(
    ("action", "score", "clicked", "downloaded", "submitted"),
    [(None, 60, "Unconfirmed", "Unconfirmed", "Unconfirmed"),
     ("clicked", 80, "Yes", "No", "Unconfirmed"),
     ("downloaded", 80, "No", "Yes", "Unconfirmed"),
     ("password", 90, "Unconfirmed", "Unconfirmed", "Password"),
     ("otp", 90, "Unconfirmed", "Unconfirmed", "One-time code")],
)
@pytest.mark.parametrize("completed", [False, True])
def test_formatter_real_scores_and_partial_answers(
    assessed_session, action, score, clicked, downloaded, submitted, completed
):
    state, service = assessed_session
    if action:
        state.apply_answer(action, service)
    if completed:
        state.complete(service)

    text = messages.ResultFormatter().format({"score": -999}, session=state)

    assert f"Rule-based score: {score}" in text
    assert f"Priority: {'Medium' if score == 60 else 'High'}" in text
    assert f"Clicked link: {clicked}" in text
    assert f"Downloaded file: {downloaded}" in text
    assert f"Information submitted: {submitted}" in text
    assert "Exposure unconfirmed" in text
    questions = ["Did you click the link / download the file?",
                 "Did you enter a password or code?"]
    assert all((question in text) is (not completed) for question in questions)
    if completed:
        assert "Report not saved. Use Retry saving." in text
        assert "Provisional" not in text
    else:
        assert "provisional" in text.lower()
        assert "not saved" in text.lower()
        assert "Finish and save" in text and "Skip unanswered" in text
        assert "30 minutes" in text and "bot restart" in text
    assert text.endswith(messages.ResultFormatter.FOOTER)


def test_formatter_confirmed_no_answers_do_not_claim_unknown(assessed_session):
    state, service = assessed_session
    state.apply_answer("neither", service)
    state.apply_answer("no_disclosure", service)

    text = messages.ResultFormatter().format({}, session=state)

    assert "Clicked link: No" in text
    assert "Downloaded file: No" in text
    assert "Information submitted: None reported" in text
    assert "unconfirmed" not in text.lower()


@pytest.mark.parametrize("saved", [False, True])
def test_formatter_completed_cache_is_authoritative(assessed_session, saved):
    state, service = assessed_session
    state.apply_answer("both", service)
    state.apply_answer("otp", service)
    state.complete(service)
    state.result = {"score": -999}
    state.exposure.update(clicked=None, downloaded=None, disclosure_answered=False)
    state.saved = saved

    text = messages.ResultFormatter().format({"score": -888}, session=state)

    assert "Rule-based score: 90" in text
    assert "Clicked link: Yes" in text and "Downloaded file: Yes" in text
    assert "Information submitted: One-time code" in text
    assert "unconfirmed" not in text.lower() and "Did you" not in text
    assert ("Report saved locally." in text) is saved
    assert ("Report not saved. Use Retry saving." in text) is (not saved)


@pytest.mark.parametrize("value", [0, 1, "yes", None])
def test_formatter_requires_identity_booleans(session, value):
    session.exposure.update(clicked=value, downloaded=value,
                            submitted_category="private secret", disclosure_answered=value)

    text = messages.ResultFormatter().format({}, session=session)

    assert "Clicked link: Unconfirmed" in text
    assert "Downloaded file: Unconfirmed" in text
    assert "Information submitted: Unconfirmed" in text
    assert "Exposure unconfirmed" in text
    assert "private secret" not in text


@pytest.mark.parametrize("completed", [False, True])
def test_formatter_is_read_only_and_saved_overrides_pending(session, monkeypatch, completed):
    session.completed = completed
    session.saved = True
    before = dict(session.__dict__)
    values = {key: deepcopy(value) for key, value in before.items() if key != "lock"}
    monkeypatch.setattr(messages, "build_exposure_keyboard", Mock(side_effect=AssertionError))
    monkeypatch.setattr("phishreport.bot.exposure.time.monotonic",
                        Mock(side_effect=AssertionError))
    for name in ("assess", "assess_with_findings", "rescore", "build_exposure_report"):
        monkeypatch.setattr(AssessmentService, name, Mock(side_effect=AssertionError))

    text = messages.ResultFormatter().format({}, session=session)

    assert "Report saved locally." in text
    assert "Did you" not in text and "Retry saving" not in text
    assert all(session.__dict__[key] is value for key, value in before.items())
    assert {key: value for key, value in session.__dict__.items() if key != "lock"} == values
    for private in (session.token, "123456", "234567", "345678", "AI findings",
                    "private message", "private sender"):
        assert private not in text


@pytest.mark.parametrize("character", ["A", "😀"])
@pytest.mark.parametrize("lifecycle", ["legacy", "pending", "completed", "saved"])
def test_formatter_bounds_whole_reply_in_utf16(session, character, lifecycle):
    result = {"score": 80, "priority": "HIGH", "reasons": [character * 6000]}
    session.result = result
    session.completed = lifecycle == "completed"
    session.saved = lifecycle == "saved"

    text = messages.ResultFormatter().format(
        result, session=None if lifecycle == "legacy" else session
    )

    assert len(text.encode("utf-16-le")) // 2 <= 4000
    assert text.encode("utf-16-le").decode("utf-16-le") == text
    assert "..." in text and "Rule-based score: 80" in text
    assert text.endswith(messages.ResultFormatter.FOOTER)
    if lifecycle == "pending":
        assert "Did you click the link / download the file?" in text
        assert "Did you enter a password or code?" in text
        assert "Exposure unconfirmed" in text and "30 minutes" in text
    elif lifecycle == "completed":
        assert "Report not saved. Use Retry saving." in text
    elif lifecycle == "saved":
        assert "Report saved locally." in text
