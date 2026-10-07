# Offline integration tests: real AI, logic and storage; fictional input and mocked HTTP.
import json
import logging
import urllib.error
from unittest.mock import MagicMock, Mock

import ai_manager
import data_manager
import main
import pytest


@pytest.fixture
def app_boundary(tmp_path, monkeypatch):
    """Keep reports/logs temporary and restore shared logger state after each test."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "fictional-integration-key")
    monkeypatch.setenv("GROQ_MODEL", "fictional/integration-model")
    logger = logging.getLogger("ai_manager")
    monkeypatch.setattr(logger, "handlers", [logging.NullHandler()])
    monkeypatch.setattr(logger, "level", logger.level)
    monkeypatch.setattr(logger, "propagate", logger.propagate)
    transport = MagicMock()
    monkeypatch.setattr(ai_manager.urllib.request, "urlopen", transport)
    monkeypatch.setattr(main.io_manager, "show_message", Mock())
    monkeypatch.setattr(main.io_manager, "display_result", Mock())
    yield transport
    for handler in list(logger.handlers):
        handler.close()


def _completed_reply(transport, findings):
    envelope = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(findings),
    }}]}
    transport.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()


def _record():
    return {"message": "PRIVATE_EMAIL: fictional account asks for a password",
            "submitted_category": "password", "clicked": False, "downloaded": False}


@pytest.mark.parametrize("failure", ["input", "timeout", "http", "incomplete", "json", "schema"])
def test_failed_assessment_never_reaches_logic_storage_or_success_display(
    app_boundary, monkeypatch, failure,
):
    record = _record()
    _completed_reply(app_boundary, {
        "credential_request": True, "suspicious": True, "insufficient_context": False,
    })
    if failure == "input":
        record["message"] = None
    elif failure == "timeout":
        app_boundary.side_effect = TimeoutError("PRIVATE_ERROR")
    elif failure == "http":
        app_boundary.side_effect = urllib.error.HTTPError(
            "https://example.test/PRIVATE_URL", 503, "PRIVATE_ERROR", {}, None,
        )
    elif failure == "incomplete":
        envelope = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        app_boundary.return_value.__enter__.return_value.read.return_value = (
            json.dumps(envelope).encode()
        )
    elif failure == "json":
        app_boundary.return_value.__enter__.return_value.read.return_value = b"PRIVATE_BODY"
    else:
        _completed_reply(app_boundary, {"suspicious": "PRIVATE_BODY"})
    original = record.copy()
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))
    evaluate, save = Mock(), Mock()
    monkeypatch.setattr(main.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(main.data_manager, "save", save)

    main.check_new_message()

    evaluate.assert_not_called()
    save.assert_not_called()
    main.io_manager.display_result.assert_not_called()
    main.io_manager.show_message.assert_called_once()
    assert "failed" in main.io_manager.show_message.call_args.args[0]
    assert "PRIVATE_" not in main.io_manager.show_message.call_args.args[0]
    assert record == original
    assert app_boundary.call_count == (0 if failure == "input" else 1)


@pytest.mark.parametrize("findings, priority", [
    ({"credential_request": True, "suspicious": True, "insufficient_context": False}, "high"),
    ({"credential_request": False, "suspicious": False, "insufficient_context": True},
     "insufficient_information"),
])
def test_successful_assessment_reaches_real_logic_and_storage(
    app_boundary, monkeypatch, findings, priority,
):
    record = _record()
    _completed_reply(app_boundary, findings)
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))

    main.check_new_message()

    saved = data_manager.load()
    assert saved == [record]
    assert saved[0]["ai"] == findings
    assert saved[0]["result"]["priority"] == priority
    assert saved[0]["result"]["checklist"]
    main.io_manager.display_result.assert_called_once_with(record["result"])
    main.io_manager.show_message.assert_not_called()
    app_boundary.assert_called_once()


def test_menu_continues_after_bad_record_then_saves_next_assessment(
    app_boundary, monkeypatch, tmp_path,
):
    findings = {"credential_request": True, "suspicious": True, "insufficient_context": False}
    _completed_reply(app_boundary, findings)
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(side_effect=["1", "1", "3"]))
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(side_effect=[
        {"message": None}, _record(),
    ]))

    main.main()

    assert main.io_manager.main_menu.call_count == 3
    assert len(data_manager.load()) == 1
    main.io_manager.display_result.assert_called_once()
    app_boundary.assert_called_once()
    log = (tmp_path / "phishreport.log").read_text(encoding="utf-8")
    assert log.count("stage=build_prompt") == 1
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log
    assert not any(isinstance(h, logging.FileHandler) for h in ai_manager.logger.handlers)


def test_configured_logging_writes_sanitised_diagnostics(app_boundary, tmp_path, capsys):
    handler = main.configure_logging()
    assert handler is not None
    app_boundary.side_effect = TimeoutError("PRIVATE_EXCEPTION")
    with pytest.raises(RuntimeError):
        ai_manager.call_api("PRIVATE_PROMPT")
    handler.flush()
    log = (tmp_path / "phishreport.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "stage=call_api" in log and "timed out" in log
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log
    assert "Traceback" not in log
    assert capsys.readouterr().err == ""


def test_unwritable_log_destination_keeps_menu_available(app_boundary, tmp_path, monkeypatch):
    (tmp_path / "phishreport.log").mkdir()
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(return_value="3"))

    main.main()

    main.io_manager.main_menu.assert_called_once()
    messages = [call.args[0] for call in main.io_manager.show_message.call_args_list]
    assert any("logging" in message.lower() for message in messages)
    assert messages[-1] == "Bye!"
    app_boundary.assert_not_called()


def test_failed_log_write_preserves_ai_error_without_traceback(app_boundary, monkeypatch, capsys):
    handler = main.configure_logging()
    stream = Mock(wraps=handler.stream)
    stream.write.side_effect = OSError("PRIVATE_DISK_ERROR")
    monkeypatch.setattr(handler, "stream", stream)
    app_boundary.side_effect = TimeoutError("PRIVATE_PROVIDER_ERROR")

    with pytest.raises(RuntimeError, match="timed out"):
        ai_manager.call_api("PRIVATE_PROMPT")

    main.io_manager.show_message.assert_called_once()
    notice = main.io_manager.show_message.call_args.args[0]
    assert "log" in notice.lower() and "PRIVATE_" not in notice
    assert capsys.readouterr().err == ""
