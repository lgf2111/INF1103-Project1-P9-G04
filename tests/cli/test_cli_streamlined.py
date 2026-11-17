"""Streamlined CLI: derive the inputs and ask only about the interaction."""

from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.io import IOManager
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager

FINDINGS = {
    "credential_request": True,
    "suspicious": True,
    "insufficient_context": False,
    "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
}


def build_app(tmp_path, terminal, feedback_service=None):
    """Compose the real CLI workflow with a stubbed AI service."""
    ai = Mock(**{"assess.return_value": dict(FINDINGS)})
    data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    app = PhishReportApp(
        IOManager(terminal),
        ai,
        LogicManager(),
        data,
        feedback_service=feedback_service,
    )
    return app, ai, data


def report(assessment_id, score, priority):
    """Return a saved version-3 report with a complete result."""
    return {
        "schema_version": 3,
        "assessment_id": assessment_id,
        "channel": "chat",
        "message": f"Fictional message {assessment_id}",
        "result": {
            "score": score,
            "priority": priority,
            "reasons": ["A fictional reason."],
            "checklist": ["A fictional action."],
        },
    }


def test_one_paste_with_a_url_and_phone_is_sms_without_input_prompts(tmp_path, monkeypatch):
    """The first required behavior: derive channel and link, never prompt for them."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.side_effect = [
        "1",
        "Call +65 9123 4567 or visit https://evil.example.test/login. ",
        "END",
        "",
        "5",
    ]
    app, ai, data = build_app(tmp_path, terminal)

    app.run()

    prompts = [call.args[0].lower() for call in terminal.read.call_args_list]
    for forbidden in ("channel", "sender", "was a link", "enter the link", "was a file"):
        assert not any(forbidden in prompt for prompt in prompts)
    record = ai.assess.call_args.args[0]
    assert record["channel"] == "sms"
    assert record["has_link"] is True
    assert record["link"] == "https://evil.example.test/login"
    assert record["sender"] == "+65 9123 4567"
    [saved] = data.load(strict=True)
    assert saved["channel"] == "sms"
    assert saved["result"]["score"] == 60
    terminal.write.assert_any_call("Detected: sms")


def test_menu_lists_exactly_five_items_and_two_views_saved_reports(tmp_path, monkeypatch):
    """The second required behavior: five items, and 2 is history, not a folder."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.return_value = "5"
    menu = IOManager(terminal)

    assert menu.main_menu() == "5"
    assert [call.args[0] for call in terminal.write.call_args_list] == [
        "\n=== PhishReport ===",
        "1. Check a message",
        "2. View saved reports",
        "3. Summarize saved reports",
        "4. Filter and export saved reports",
        "5. Quit",
    ]

    terminal.read.reset_mock()
    terminal.write.reset_mock()
    app, _, _ = build_app(tmp_path, terminal)
    view, folder = Mock(), Mock()
    monkeypatch.setattr(app, "view_reports", view)
    monkeypatch.setattr(app._io_manager, "collect_input_from_folder", folder)
    monkeypatch.setattr(app._io_manager, "main_menu", Mock(side_effect=["2", "5"]))

    app.run()

    view.assert_called_once_with()
    folder.assert_not_called()


def test_upload_at_the_menu_prompt_reaches_the_browser_uploader(tmp_path, monkeypatch):
    """Typing upload keeps the browser route without a numbered slot."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.side_effect = [
        "upload",
        "",
        "5",
    ]
    app, ai, data = build_app(tmp_path, terminal)
    receive = Mock(return_value={
        "filename": "fictional.eml",
        "content": (
            b"From: fictional@example.test\r\n"
            b"Subject: Fictional notice\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Verify your account."
        ),
    })
    monkeypatch.setattr(
        "phishreport.cli.web_upload.BrowserUploadService.receive_upload", receive,
    )

    app.run()

    receive.assert_called_once_with()
    [saved] = data.load(strict=True)
    assert saved["channel"] == "email"
    assert ai.assess.call_args.args[0]["sender"] == "fictional@example.test"


def test_feedback_at_the_menu_corrects_the_newest_report_without_adding_one(tmp_path, monkeypatch):
    """The menu correction reuses FeedbackService and leaves history unchanged."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.side_effect = ["feedback", "3", "low", "Fictional correction", "5"]
    store = FeedbackStore(tmp_path / "feedback.json")
    app, _, data = build_app(
        tmp_path, terminal, feedback_service=FeedbackService(store),
    )
    older = report("assessment-older", 60, "MEDIUM")
    newest = report("assessment-newest", 80, "HIGH")
    data.save(older)
    data.save(newest)

    app.run()

    [feedback] = store.load()
    assert feedback.assessment_id == newest["assessment_id"]
    assert feedback.category == "incorrect_priority"
    assert feedback.corrected_priority == "LOW"
    assert feedback.comment == "Fictional correction"
    assert [record["assessment_id"] for record in data.load(strict=True)] == [
        older["assessment_id"],
        newest["assessment_id"],
    ]
    terminal.write.assert_any_call("Thank you. Your feedback was saved for review.")


def test_skipping_the_post_verdict_checklist_keeps_the_plain_report(tmp_path, monkeypatch):
    """A skipped checklist answer is unconfirmed, not a confirmed no."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.side_effect = [
        "1",
        "A fictional message asks for a password.",
        "END",
        "",
        "5",
    ]
    app, _, data = build_app(tmp_path, terminal)

    app.run()

    [saved] = data.load(strict=True)
    assert "exposure" not in saved
    assert saved["result"]["score"] == 60


def test_post_verdict_password_selection_rescores_to_ninety(tmp_path, monkeypatch):
    """The checklist answer maps to the disclosure rule after the verdict."""
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    terminal.read.side_effect = [
        "1",
        "A fictional message asks for a password.",
        "END",
        "3",
        "5",
    ]
    app, _, data = build_app(tmp_path, terminal)

    app.run()

    [saved] = data.load(strict=True)
    assert saved["exposure"] == {
        "clicked": False,
        "downloaded": False,
        "submitted_category": "password",
        "disclosure_answered": True,
    }
    assert saved["result"]["score"] == 90
    assert saved["result"]["priority"] == "HIGH"


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("1", {"clicked": True, "downloaded": False, "submitted_category": None}),
        ("2", {"clicked": False, "downloaded": True, "submitted_category": None}),
        ("3", {"clicked": False, "downloaded": False, "submitted_category": "password"}),
        ("4", {"clicked": False, "downloaded": False, "submitted_category": "otp"}),
        (
            "1,3,4",
            {"clicked": True, "downloaded": False, "submitted_category": "password"},
        ),
    ],
)
def test_numbered_exposure_accepts_multiple_answers(answer, expected):
    """The non-TTY prompt accepts any combination of 1-4."""
    terminal = Mock()
    terminal.read.return_value = answer

    result = IOManager(terminal).collect_exposure()

    assert {key: result[key] for key in expected} == expected
    assert result["disclosure_answered"] is True
    assert "1,3,4 + Enter, or Enter to skip" in terminal.read.call_args.args[0]


def test_blank_numbered_exposure_is_unconfirmed():
    """Blank ends the checklist without inventing an exposure answer."""
    terminal = Mock()
    terminal.read.return_value = ""

    assert IOManager(terminal).collect_exposure() is None
