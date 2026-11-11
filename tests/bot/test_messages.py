"""Exposure keyboard payloads reflect explicit answers without changing state."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from telegram import InlineKeyboardMarkup

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot import messages
from phishreport.bot.exposure import ExposureSession


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
