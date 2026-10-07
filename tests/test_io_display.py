import json

import io_manager
import logic_manager
import main


def test_display_result_shows_assessment(capsys):
    io_manager.display_result({
        "priority": "insufficient_information",
        "score": 30,
        "reasons": ["More context is required."],
        "checklist": ["Give more details."],
    })
    output = capsys.readouterr().out
    assert "Priority: Insufficient Information" in output
    assert "Rule-based score: 30" in output
    assert "More context is required." in output
    assert "1. Give more details." in output


def test_display_record_shows_complete_details(capsys):
    message = "Fictional message with enough words to exceed the preview limit of fifty characters."
    io_manager.display_record({
        "channel": "email",
        "sender": None,
        "message": message,
        "link": None,
        "file_name": "example.txt",
        "clicked": False,
        "downloaded": True,
        "submitted_category": "otp",
        "result": {"priority": "high", "score": 90, "checklist": ["Tell IT."]},
    })
    output = capsys.readouterr().out
    assert message in output
    assert "Sender: Unknown" in output
    assert "Included file: example.txt" in output
    assert "Clicked link: No" in output
    assert "Downloaded file: Yes" in output
    assert "Information submitted: One-time code" in output
    assert "Priority: High" in output


def test_display_record_without_assessment(capsys):
    io_manager.display_record({"message": "Older record"})
    output = capsys.readouterr().out
    assert "No assessment available." in output
    assert "No Clear Indicators" not in output


def test_display_list_shows_numbered_summaries(capsys):
    io_manager.display_list([
        {"channel": "sms", "message": "Line one\nLine two",
         "result": {"priority": "review", "score": 50}},
        {"channel": "email", "message": "Second fictional message",
         "result": {"priority": "high", "score": 90}},
    ])
    output = capsys.readouterr().out
    assert "1. SMS | Review | Score: 50" in output
    assert "2. Email | High | Score: 90" in output
    assert "Line one Line two" in output


def test_display_list_handles_empty_history(capsys):
    io_manager.display_list([])
    assert "No saved reports yet." in capsys.readouterr().out


def test_display_result_keeps_safety_wording(capsys):
    record = {"ai": {"credential_request": False, "suspicious": False,
                     "insufficient_context": False}}
    io_manager.display_result(logic_manager.evaluate(record))
    assert "This does not mean it is safe." in capsys.readouterr().out


def test_view_saved_reports_displays_full_details(monkeypatch, capsys):
    message = "A fictional saved message longer than fifty characters with a visible ending."
    monkeypatch.setattr(main.data_manager, "load", lambda: [{"message": message}])
    main.view_saved_reports()
    output = capsys.readouterr().out
    assert "=== Saved reports ===" in output
    assert "Report 1" in output
    assert message in output


def test_check_new_message_displays_full_record(monkeypatch, capsys):
    message = "Fictional SMS message for the offline display integration test."
    record = {"channel": "sms", "message": message, "clicked": False,
              "downloaded": False, "submitted_category": None}
    findings = {"credential_request": False, "suspicious": False,
                "insufficient_context": False}
    saved = []
    monkeypatch.setattr(main.io_manager, "collect_input", lambda: record)
    monkeypatch.setattr(main.ai_manager, "call_api", lambda _: json.dumps(findings))
    monkeypatch.setattr(main.data_manager, "save", saved.append)
    main.check_new_message()
    output = capsys.readouterr().out
    assert "Channel: SMS" in output
    assert message in output
    assert "Rule-based score: 10" in output
    assert saved[0]["ai"] == findings
    assert saved[0]["result"]["priority"] == "no_clear_indicators"
