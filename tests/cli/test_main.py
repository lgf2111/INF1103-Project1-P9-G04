"""CLI integration with real AI, logic and JSON; fictional input and mocked HTTP."""

import base64
import json
import logging
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, Mock, call

import pytest

from phishreport.ai import GroqClient, groq_client
from phishreport.cli import main, web_upload
from phishreport.data import DataManager

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"


# ============================================================================
# Main
# ============================================================================
# Offline integration tests: real AI/logic/JSON; fictional input and mocked HTTP.


def test_cli_app_uses_its_own_managers_for_each_assessment():
    """Two applications keep their own input, assessment, storage and display calls."""

    def build_app(message):
        record = {"channel": "email", "message": message}
        findings = {"suspicious": True}
        result = {"score": 45, "priority": "MEDIUM"}
        collaborators = Mock()
        collaborators.io.collect_input.return_value = record
        collaborators.ai.assess.return_value = findings
        collaborators.logic.evaluate.return_value = result
        app = main.PhishReportApp(
            io_manager=collaborators.io,
            ai_manager=collaborators.ai,
            logic_manager=collaborators.logic,
            data_manager=collaborators.data,
        )
        expected = [
            call.io.collect_input(),
            call.ai.assess(record),
            call.logic.evaluate({**record, "ai": findings}),
            call.data.save({"schema_version": 2, **record, "result": result}),
            call.io.display_result(result),
        ]
        return app, collaborators, expected

    first, first_managers, first_calls = build_app("First fictional message")
    second, second_managers, second_calls = build_app("Second fictional message")
    first.check_message()
    second.check_message()
    assert first_managers.mock_calls == first_calls
    assert second_managers.mock_calls == second_calls


@pytest.fixture
def main_app_boundary(cli, tmp_path, monkeypatch):
    """Keep reports/logs temporary and restore shared logger state after each test."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "fictional-integration-key")
    monkeypatch.setenv("GROQ_MODEL", "fictional/integration-model")
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)
    for name in ("ai_manager", "data_manager"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [logging.NullHandler()])
        monkeypatch.setattr(logger, "level", logger.level)
        monkeypatch.setattr(logger, "propagate", logger.propagate)
    monkeypatch.setattr(groq_client.time, "sleep", Mock())
    transport = MagicMock()
    monkeypatch.setattr(groq_client.urllib.request, "urlopen", transport)
    monkeypatch.setattr(cli.io_manager, "show_message", Mock())
    monkeypatch.setattr(cli.io_manager, "display_result", Mock())
    # Reset the central logging so each test configures a fresh file logger in
    # its own tmp_path, and restore the root logger afterwards.
    main.logging_setup._configured = False
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    yield transport
    for handler in list(root.handlers):
        handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    main.logging_setup._configured = False
    for name in ("ai_manager", "data_manager"):
        for handler in list(logging.getLogger(name).handlers):
            handler.close()


def main_completed_reply(transport, data):
    envelope = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(data),
                },
            }
        ]
    }
    transport.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()


def main_details():
    return {"emails": [], "phone_numbers": [], "ip_addresses": []}


def main_findings():
    return {
        "credential_request": True,
        "suspicious": True,
        "insufficient_context": False,
        "details": main_details(),
    }


def main_successful_reply(transport):
    main_completed_reply(transport, main_findings())


def main_record():
    return {
        "channel": "email",
        "sender": None,
        "message": "PRIVATE_EMAIL: fictional account asks for a password",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "submitted_category": "password",
        "clicked": False,
        "downloaded": False,
    }


@pytest.mark.parametrize("invented_contact", [False, True])
@pytest.mark.parametrize("disclosure, expected_score", [("no", 60), ("otp", 90)])
def test_main_browser_html_email_uses_canonical_source_before_logic_and_save(
    cli, main_app_boundary,
    monkeypatch,
    invented_contact,
    disclosure,
    expected_score,
):

    raw = (
        b"From: fictional@example.test\r\nSubject: Fictional security notice\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<p>Reply to a1@example.test with your password</p>"
        b'<a href="https://credential.example.test/login">Verify account</a>'
    )
    monkeypatch.setattr(
        web_upload,
        "start_and_wait_for_upload",
        Mock(
            return_value={
                "filename": "fictional.eml",
                "content": raw,
            }
        ),
    )
    findings = main_findings()
    findings["details"]["emails"] = [
        "absent@example.test" if invented_contact else "a1@example.test"
    ]
    main_completed_reply(main_app_boundary, findings)
    answers = iter(["no", "no", disclosure])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.app.upload_file()
    assert main_app_boundary.call_count == 1
    records = DataManager().load()
    if invented_contact:
        assert records == []
        cli.io_manager.display_result.assert_not_called()
    else:
        assert len(records) == 1
        message = records[0]["message"]
        assert "a1@example.test" in message
        assert "https://credential.example.test/login" in message
        assert "<p>" not in message and "Content-Type:" not in message
        assert records[0]["result"]["score"] == expected_score
        cli.io_manager.display_result.assert_called_once_with(records[0]["result"])


@pytest.mark.parametrize(
    "content",
    [
        b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Invalid \xff</p>",
        b"Content-Type: text/html\r\n\r\n<script>No message</script>",
    ],
)
def test_main_invalid_browser_email_stops_before_ai_or_save(
    cli, main_app_boundary, monkeypatch, content
):

    monkeypatch.setattr(
        web_upload,
        "start_and_wait_for_upload",
        Mock(
            return_value={
                "filename": "fictional.eml",
                "content": content,
            }
        ),
    )
    cli.app.upload_file()
    main_app_boundary.assert_not_called()
    cli.io_manager.display_result.assert_not_called()
    assert DataManager().load() == []


@pytest.mark.parametrize("invented_contact", [False, True])
def test_main_eml_retry_and_decoded_source_reach_real_pipeline(
    cli, main_app_boundary,
    monkeypatch,
    tmp_path,
    invented_contact,
):
    bad = tmp_path / "malformed.eml"
    bad.write_bytes(b"Content-Type: text/plain; charset=utf-8\r\n\r\nInvalid \xff")
    good = tmp_path / "encoded.eml"
    body = "Fictional contact a1@example.test asks for a password."
    good.write_bytes(
        b"From: fictional@example.test\r\nSubject: Fictional request\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\n" + base64.b64encode(body.encode())
    )
    findings = main_findings()
    findings["details"]["emails"] = [
        "absent@example.test" if invented_contact else "a1@example.test"
    ]
    main_completed_reply(main_app_boundary, findings)
    # Keep the saved-config file inside tmp_path so it doesn't touch the repo.
    monkeypatch.chdir(tmp_path)
    # Option 2 now picks a .eml from a saved folder. First run asks for the
    # folder; then the newest files are listed (encoded.eml is newer than
    # malformed.eml). Pick the malformed one first (retry), then the good one.
    answers = iter(["2", str(tmp_path), "2", "1", "no", "no", "no", "5"])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    cli.app.run()
    assert prompts[0] == "Choose 1-5: "
    assert any("email folder" in prompt.lower() for prompt in prompts)
    assert not any(
        "channel" in prompt.lower() or "input method" in prompt.lower() for prompt in prompts
    )
    assert main_app_boundary.call_count == 1
    prompt = json.loads(main_app_boundary.call_args.args[0].data)["messages"][0]["content"]
    assert str(good) not in prompt
    records = DataManager().load()
    if invented_contact:
        assert records == []
        cli.io_manager.display_result.assert_not_called()
    else:
        assert len(records) == 1
        assert records[0]["message"] == "Subject: Fictional request\n\n" + body
        assert records[0]["result"]["score"] == 60
        cli.io_manager.display_result.assert_called_once_with(records[0]["result"])


@pytest.mark.parametrize("failure", ["input", "timeout", "http", "incomplete", "json", "schema"])
def test_main_failed_assessment_never_reaches_logic_storage_or_success_display(
    cli, main_app_boundary,
    monkeypatch,
    failure,
):
    record = main_record()
    main_completed_reply(main_app_boundary, main_findings())
    if failure == "input":
        record["message"] = None
    elif failure == "timeout":
        main_app_boundary.side_effect = TimeoutError("PRIVATE_ERROR")
    elif failure == "http":
        main_app_boundary.side_effect = urllib.error.HTTPError(
            "https://example.test/PRIVATE_URL",
            503,
            "PRIVATE_ERROR",
            {},
            None,
        )
    elif failure == "incomplete":
        envelope = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        main_app_boundary.return_value.__enter__.return_value.read.return_value = json.dumps(
            envelope
        ).encode()
    elif failure == "json":
        main_app_boundary.return_value.__enter__.return_value.read.return_value = b"PRIVATE_BODY"
    else:
        main_completed_reply(main_app_boundary, {"suspicious": "PRIVATE_BODY"})
    original = record.copy()
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))
    evaluate, save = Mock(), Mock()
    monkeypatch.setattr(cli.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(cli.data_manager, "save", save)

    cli.app.check_message()

    evaluate.assert_not_called()
    save.assert_not_called()
    cli.io_manager.display_result.assert_not_called()
    cli.io_manager.show_message.assert_called_once()
    assert "failed" in cli.io_manager.show_message.call_args.args[0]
    assert "PRIVATE_" not in cli.io_manager.show_message.call_args.args[0]
    assert record == original
    expected_calls = 0 if failure == "input" else 2 if failure in ("timeout", "http") else 1
    assert main_app_boundary.call_count == expected_calls


def test_main_successful_assessment_reaches_real_logic_and_storage(
    cli, main_app_boundary, monkeypatch
):
    record = main_record()
    original = record.copy()
    main_successful_reply(main_app_boundary)
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))

    cli.app.check_message()

    saved = DataManager().load()
    assert saved == [
        {
            "schema_version": 2,
            "channel": record["channel"],
            "message": record["message"],
            "result": cli.io_manager.display_result.call_args.args[0],
        }
    ]
    assert record == original
    result = cli.io_manager.display_result.call_args.args[0]
    assert result["score"] == 90 and result["priority"] == "HIGH"
    assert result["checklist"]
    cli.io_manager.display_result.assert_called_once()
    cli.io_manager.show_message.assert_not_called()
    assert main_app_boundary.call_count == 1


def test_main_menu_continues_after_bad_record_then_saves_next_assessment(
    cli, main_app_boundary,
    monkeypatch,
    tmp_path,
):
    main_successful_reply(main_app_boundary)
    monkeypatch.setattr(cli.io_manager, "main_menu", Mock(side_effect=["1", "1", "5"]))
    monkeypatch.setattr(
        cli.io_manager,
        "collect_input",
        Mock(
            side_effect=[
                {"message": None},
                main_record(),
            ]
        ),
    )

    cli.app.run()

    assert cli.io_manager.main_menu.call_count == 3
    assert len(DataManager().load()) == 1
    cli.io_manager.display_result.assert_called_once()
    assert main_app_boundary.call_count == 1
    log = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert log.count("stage=build_prompt") == 1
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log


def test_main_configured_logging_writes_sanitised_diagnostics(main_app_boundary, tmp_path, capsys):
    # Default level (no LOG_LEVEL=DEBUG): sanitised, no traceback, no secrets.
    assert main.logging_setup.setup_logging() is True
    main_app_boundary.side_effect = TimeoutError("PRIVATE_EXCEPTION")
    with pytest.raises(RuntimeError):
        GroqClient().complete("PRIVATE_PROMPT")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "stage=call_api" in log and "timed out" in log
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log
    assert "Traceback" not in log
    assert capsys.readouterr().err == ""


def test_main_unwritable_log_destination_keeps_menu_available(
    cli, main_app_boundary, tmp_path, monkeypatch
):
    # A file named "logs" makes os.makedirs("logs") fail, so the file log can't
    # open - the app must still run and warn about logging being unavailable.
    (tmp_path / "logs").write_text("not a directory")
    monkeypatch.setattr(cli.io_manager, "main_menu", Mock(return_value="5"))

    cli.app.run()

    cli.io_manager.main_menu.assert_called_once()
    messages = [call.args[0] for call in cli.io_manager.show_message.call_args_list]
    assert any("logging" in message.lower() for message in messages)
    assert messages[-1] == "Bye!"
    main_app_boundary.assert_not_called()


def test_main_failed_log_write_does_not_crash_or_leak(main_app_boundary, monkeypatch, capsys):
    # Even if writing to the log file fails, the AI error must still surface and
    # nothing private may reach the terminal.
    assert main.logging_setup.setup_logging() is True
    for handler in logging.getLogger().handlers:
        if hasattr(handler, "stream"):
            stream = Mock(wraps=handler.stream)
            stream.write.side_effect = OSError("PRIVATE_DISK_ERROR")
            monkeypatch.setattr(handler, "stream", stream)
    # logging must not raise on a write error (default behaviour).
    monkeypatch.setattr(logging, "raiseExceptions", False)
    main_app_boundary.side_effect = TimeoutError("PRIVATE_PROVIDER_ERROR")

    with pytest.raises(RuntimeError, match="timed out"):
        GroqClient().complete("PRIVATE_PROMPT")

    captured = capsys.readouterr()
    assert "PRIVATE_" not in captured.out and "PRIVATE_" not in captured.err


@pytest.mark.parametrize("failure", ["missing-findings", "detail-type", "invented-contact"])
def test_main_combined_validation_failure_stops_before_logic_and_storage(
    cli, main_app_boundary,
    monkeypatch,
    failure,
):
    data = main_findings()
    if failure == "missing-findings":
        data = main_details()
    elif failure == "detail-type":
        data["details"]["emails"] = "PRIVATE_VALUE"
    else:
        data["details"]["emails"] = ["fictional@example.test"]
    main_completed_reply(main_app_boundary, data)
    record = main_record()
    original = record.copy()
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))
    evaluate, save = Mock(), Mock()
    monkeypatch.setattr(cli.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(cli.data_manager, "save", save)

    cli.app.check_message()

    evaluate.assert_not_called()
    save.assert_not_called()
    cli.io_manager.display_result.assert_not_called()
    cli.io_manager.show_message.assert_called_once()
    assert "PRIVATE_" not in cli.io_manager.show_message.call_args.args[0]
    assert main_app_boundary.call_count == 1
    assert record == original


def test_main_combined_caller_passes_validated_findings_to_logic_once(
    cli, main_app_boundary, monkeypatch
):
    record = main_record()
    data = main_findings()
    record["message"] += "; contact fictional@example.test."
    data["details"]["emails"] = ["fictional@example.test"]
    main_completed_reply(main_app_boundary, data)
    # Any attempted second read would fail; no formatting request is needed.
    main_app_boundary.return_value.__enter__.return_value.read.side_effect = [
        main_app_boundary.return_value.__enter__.return_value.read.return_value,
        AssertionError("Unexpected second API response"),
    ]
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))
    result = {"score": 90, "priority": "HIGH", "reasons": [], "checklist": []}
    evaluate = Mock(return_value=result)
    save = Mock()
    monkeypatch.setattr(cli.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(cli.data_manager, "save", save)

    cli.app.check_message()

    evaluate.assert_called_once_with({**record, "ai": data})
    assert "ai" not in record
    save.assert_called_once()
    assert save.call_args.args[0] == {
        "schema_version": 2,
        "channel": record["channel"],
        "message": record["message"],
        "result": result,
    }
    cli.io_manager.display_result.assert_called_once_with(result)
    main_app_boundary.assert_called_once()


def test_main_combined_caller_uses_ai_findings_for_the_same_unexposed_input(
    cli, main_app_boundary, monkeypatch
):
    record = main_record()
    record["submitted_category"] = None
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))
    for suspicious, credential, expected in ((False, False, 10), (True, True, 60)):
        data = main_findings()
        data.update(suspicious=suspicious, credential_request=credential)
        main_completed_reply(main_app_boundary, data)
        cli.app.check_message()
        assert cli.io_manager.display_result.call_args.args[0]["score"] == expected
    assert main_app_boundary.call_count == 2  # two records, one request each
    assert len(DataManager().load()) == 2


def test_main_configured_storage_logging_uses_application_file(
    cli, main_app_boundary, tmp_path, monkeypatch
):
    (tmp_path / "reports.json").write_text("{PRIVATE_BROKEN")
    monkeypatch.setattr(cli.io_manager, "main_menu", Mock(return_value="5"))
    cli.app.run()
    text = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "data_manager" in text and "Could not read local report history" in text
    # Default (non-debug) logging must not leak the broken file contents.
    assert "PRIVATE" not in text
    # The corrupt history must be preserved, never overwritten.
    assert (tmp_path / "reports.json").read_text() == "{PRIVATE_BROKEN"


def test_main_recovered_timeout_saves_and_displays_only_one_assessment(
    cli, main_app_boundary, monkeypatch
):
    record = main_record()
    main_successful_reply(main_app_boundary)
    main_app_boundary.side_effect = [TimeoutError("PRIVATE_ERROR"), main_app_boundary.return_value]
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=record))

    cli.app.check_message()

    assert main_app_boundary.call_count == 2
    saved = DataManager().load()
    assert len(saved) == 1
    assert saved[0] == {
        "schema_version": 2,
        "channel": record["channel"],
        "message": record["message"],
        "result": cli.io_manager.display_result.call_args.args[0],
    }
    cli.io_manager.display_result.assert_called_once()
    cli.io_manager.show_message.assert_not_called()


def test_main_timeout_fallback_reaches_real_logic_and_saves_once(
    cli, main_app_boundary, monkeypatch
):
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fictional/faster")
    main_successful_reply(main_app_boundary)
    main_app_boundary.side_effect = [TimeoutError(), main_app_boundary.return_value]
    monkeypatch.setattr(cli.io_manager, "collect_input", Mock(return_value=main_record()))

    cli.app.check_message()

    assert main_app_boundary.call_count == 2
    assert json.loads(main_app_boundary.call_args.args[0].data)["model"] == "fictional/faster"
    saved = DataManager().load()
    assert saved == [
        {
            "schema_version": 2,
            "channel": main_record()["channel"],
            "message": main_record()["message"],
            "result": cli.io_manager.display_result.call_args.args[0],
        }
    ]
    cli.io_manager.display_result.assert_called_once()
    cli.io_manager.show_message.assert_not_called()


@pytest.mark.parametrize("choice, handler_name", [("3", "upload_file"), ("4", "view_reports")])
def test_main_menu_routes_upload_and_saved_reports(
    cli, main_app_boundary, monkeypatch, choice, handler_name
):
    handler = Mock()
    monkeypatch.setattr(cli.app, handler_name, handler)
    monkeypatch.setattr(cli.io_manager, "main_menu", Mock(side_effect=[choice, "5"]))

    cli.app.run()

    handler.assert_called_once_with()
    main_app_boundary.assert_not_called()
