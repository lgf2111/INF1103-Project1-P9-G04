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
        {"channel": "chat", "message": "Database report",
         "priority": "MEDIUM", "score": 40},
        {"channel": "email", "message": "Legacy row",
         "priority": None, "score": None},
    ])
    output = capsys.readouterr().out
    assert "1. SMS | Review | Score: 50" in output
    assert "2. Email | High | Score: 90" in output
    assert "3. Chat | Medium | Score: 40" in output
    assert "4. Email | Unavailable | Score: Unavailable" in output
    assert "Line one Line two" in output


def test_display_list_handles_empty_history(capsys):
    io_manager.display_list([])
    assert "No saved reports yet." in capsys.readouterr().out


def test_display_result_keeps_safety_wording(capsys):
    record = {
        "channel": "email",
        "sender": None,
        "message": "Test message",
        "has_link": False,
        "has_file": False,
        "link": None,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }
    details = {
        "emails": [],
        "phone_numbers": [],
        "ip_addresses": []
    }
    record["ai"] = {"credential_request": False, "suspicious": False,
                    "insufficient_context": False, "details": details}
    io_manager.display_result(logic_manager.evaluate(record))
    # Updated assertion to match the new LOW priority checklist
    assert "Remain cautious." in capsys.readouterr().out

def test_view_saved_reports_displays_full_details(monkeypatch, capsys):
    message = "A fictional saved message."  # Short enough to not be truncated
    record = {
        "channel": "email",
        "message": message,
        "result": {"priority": "HIGH", "score": 50}
    }

    monkeypatch.setattr(main.data_manager, "fetch",
                       lambda: (_ for _ in ()).throw(RuntimeError("PostgreSQL unavailable")))
    monkeypatch.setattr(main.data_manager, "load", lambda: [record])

    main.view_reports()
    output = capsys.readouterr().out

    assert "=== Saved reports ===" in output
    assert "1. Email" in output
    assert message in output

def test_check_new_message_displays_full_record(monkeypatch, capsys):
    message = "Fictional SMS message for the offline display integration test."
    record = {
        "channel": "sms",
        "sender": None,
        "message": message,
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }
    details = {"emails": [], "phone_numbers": [], "ip_addresses": []}
    findings = {"credential_request": False, "suspicious": False,
                "insufficient_context": False, "details": details}
    saved = []
    api_calls = []

    def mock_call_api(prompt):
        """Return combined findings and extraction from one request."""
        api_calls.append(prompt)
        return json.dumps(findings)

    monkeypatch.setattr(main.io_manager, "collect_input", lambda: record)
    monkeypatch.setattr(main.ai_manager, "call_api", mock_call_api)
    monkeypatch.setattr(main.data_manager, "save", saved.append)

    main.check_message()
    output = capsys.readouterr().out

    # The new implementation displays the assessment result
    assert "Priority:" in output
    assert "Rule-based score:" in output  # Changed from "Score:"
    assert "Recommended actions:" in output

    # Verify the saved data structure
    assert len(saved) == 1
    assert saved[0]["channel"] == "sms"
    assert saved[0]["message"] == message
    assert saved[0]["details"] == details

    assert len(api_calls) == 1
