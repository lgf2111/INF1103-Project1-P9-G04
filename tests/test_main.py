# Offline integration tests: real AI/logic/JSON; fictional input and mocked HTTP.
import base64
import http.client
import json
import logging
import threading
import urllib.error
from unittest.mock import MagicMock, Mock

import ai_manager
import ai_manager as ai_client
import data_manager
import main
import pytest


@pytest.fixture
def app_boundary(tmp_path, monkeypatch):
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
    monkeypatch.setattr(ai_client.time, "sleep", Mock())
    transport = MagicMock()
    monkeypatch.setattr(ai_manager.urllib.request, "urlopen", transport)
    monkeypatch.setattr(main.io_manager, "show_message", Mock())
    monkeypatch.setattr(main.io_manager, "display_result", Mock())
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


def _completed_reply(transport, data):
    envelope = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(data),
    }}]}
    transport.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()


def _details():
    return {"emails": [], "phone_numbers": [], "ip_addresses": []}


def _findings():
    return {"credential_request": True, "suspicious": True, "insufficient_context": False,
            "details": _details()}


def _successful_reply(transport):
    _completed_reply(transport, _findings())


def _record():
    return {
        "channel": "email", "sender": None,
        "message": "PRIVATE_EMAIL: fictional account asks for a password",
        "has_link": False, "link": None, "has_file": False, "file_name": None,
        "submitted_category": "password", "clicked": False, "downloaded": False,
    }


@pytest.mark.parametrize("invented_contact", [False, True])
@pytest.mark.parametrize("disclosure, expected_score", [("no", 60), ("otp", 90)])
def test_browser_html_email_uses_canonical_source_before_logic_and_save(
    app_boundary, monkeypatch, invented_contact, disclosure, expected_score,
):
    import web_upload

    raw = (b"From: fictional@example.test\r\nSubject: Fictional security notice\r\n"
           b"Content-Type: text/html; charset=utf-8\r\n\r\n"
           b'<p>Reply to a1@example.test with your password</p>'
           b'<a href="https://credential.example.test/login">Verify account</a>')
    monkeypatch.setattr(web_upload, "start_and_wait_for_upload", Mock(return_value={
        "filename":"fictional.eml", "content":raw,
    }))
    findings = _findings()
    findings["details"]["emails"] = [
        "absent@example.test" if invented_contact else "a1@example.test"
    ]
    _completed_reply(app_boundary, findings)
    answers = iter(["no", "no", disclosure])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    main.upload_file()
    assert app_boundary.call_count == 1
    records = data_manager.load()
    if invented_contact:
        assert records == []
        main.io_manager.display_result.assert_not_called()
    else:
        assert len(records) == 1
        message = records[0]["message"]
        assert "a1@example.test" in message
        assert "https://credential.example.test/login" in message
        assert "<p>" not in message and "Content-Type:" not in message
        assert records[0]["result"]["score"] == expected_score
        main.io_manager.display_result.assert_called_once_with(records[0]["result"])


@pytest.mark.parametrize("content", [
    b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Invalid \xff</p>",
    b"Content-Type: text/html\r\n\r\n<script>No message</script>",
])
def test_invalid_browser_email_stops_before_ai_or_save(app_boundary, monkeypatch, content):
    import web_upload

    monkeypatch.setattr(web_upload, "start_and_wait_for_upload", Mock(return_value={
        "filename":"fictional.eml", "content":content,
    }))
    main.upload_file()
    app_boundary.assert_not_called()
    main.io_manager.display_result.assert_not_called()
    assert data_manager.load() == []


def test_real_browser_http_to_html_ai_logic_and_json(app_boundary, monkeypatch):
    import web_upload

    ready = threading.Event()
    servers, errors = [], []
    original = web_upload.http.server.HTTPServer

    def make_server(address, handler):
        server = original(address, handler)
        servers.append(server)
        ready.set()
        return server

    def run_upload():
        try:
            main.upload_file()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(web_upload, "BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(web_upload, "PORT", 0)
    monkeypatch.setattr(web_upload.http.server, "HTTPServer", make_server)
    answers = iter(["no", "no", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    _successful_reply(app_boundary)
    raw = (b"Content-Type: text/html\r\n\r\n<p>Fictional password request</p>"
           b'<a href="https://credential.example.test">Verify</a>')
    body = (b'--x\r\nContent-Disposition: form-data; name="file"; filename="test.eml"'
            b'\r\nContent-Type: application/octet-stream\r\n\r\n' + raw + b'\r\n--x--\r\n')
    worker = threading.Thread(target=run_upload, daemon=True)
    worker.start()
    assert ready.wait(5)
    connection = http.client.HTTPConnection("127.0.0.1", servers[0].server_port, timeout=5)
    connection.request("POST", "/", body=body,
                       headers={"Content-Type":"multipart/form-data; boundary=x"})
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    worker.join(5)
    assert not worker.is_alive() and not errors
    assert app_boundary.call_count == 1
    saved = data_manager.load()
    assert len(saved) == 1 and saved[0]["result"]["score"] == 60
    assert "https://credential.example.test" in saved[0]["message"]
    assert "Content-Type:" not in saved[0]["message"]
    main.io_manager.display_result.assert_called_once_with(saved[0]["result"])


@pytest.mark.parametrize("invented_contact", [False, True])
def test_eml_retry_and_decoded_source_reach_real_pipeline(
    app_boundary, monkeypatch, tmp_path, invented_contact,
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
    findings = _findings()
    findings["details"]["emails"] = [
        "absent@example.test" if invented_contact else "a1@example.test"
    ]
    _completed_reply(app_boundary, findings)
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
    main.main()
    assert prompts[0] == "Choose 1-5: "
    assert any("email folder" in prompt.lower() for prompt in prompts)
    assert not any("channel" in prompt.lower() or "input method" in prompt.lower()
                   for prompt in prompts)
    assert app_boundary.call_count == 1
    prompt = json.loads(app_boundary.call_args.args[0].data)["messages"][0]["content"]
    assert str(good) not in prompt
    records = data_manager.load()
    if invented_contact:
        assert records == []
        main.io_manager.display_result.assert_not_called()
    else:
        assert len(records) == 1
        assert records[0]["message"] == "Subject: Fictional request\n\n" + body
        assert records[0]["result"]["score"] == 60
        main.io_manager.display_result.assert_called_once_with(records[0]["result"])


@pytest.mark.parametrize("failure", ["input", "timeout", "http", "incomplete", "json", "schema"])
def test_failed_assessment_never_reaches_logic_storage_or_success_display(
    app_boundary, monkeypatch, failure,
):
    record = _record()
    _completed_reply(app_boundary, _findings())
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

    main.check_message()

    evaluate.assert_not_called()
    save.assert_not_called()
    main.io_manager.display_result.assert_not_called()
    main.io_manager.show_message.assert_called_once()
    assert "failed" in main.io_manager.show_message.call_args.args[0]
    assert "PRIVATE_" not in main.io_manager.show_message.call_args.args[0]
    assert record == original
    expected_calls = 0 if failure == "input" else 2 if failure in ("timeout", "http") else 1
    assert app_boundary.call_count == expected_calls


def test_successful_assessment_reaches_real_logic_and_storage(app_boundary, monkeypatch):
    record = _record()
    original = record.copy()
    _successful_reply(app_boundary)
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))

    main.check_message()

    saved = data_manager.load()
    assert saved == [{"schema_version": 2, "channel": record["channel"],
                      "message": record["message"],
                      "result": main.io_manager.display_result.call_args.args[0]}]
    assert record == original
    result = main.io_manager.display_result.call_args.args[0]
    assert result["score"] == 90 and result["priority"] == "HIGH"
    assert result["checklist"]
    main.io_manager.display_result.assert_called_once()
    main.io_manager.show_message.assert_not_called()
    assert app_boundary.call_count == 1


def test_menu_continues_after_bad_record_then_saves_next_assessment(
    app_boundary, monkeypatch, tmp_path,
):
    _successful_reply(app_boundary)
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(side_effect=["1", "1", "5"]))
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(side_effect=[
        {"message": None}, _record(),
    ]))

    main.main()

    assert main.io_manager.main_menu.call_count == 3
    assert len(data_manager.load()) == 1
    main.io_manager.display_result.assert_called_once()
    assert app_boundary.call_count == 1
    log = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert log.count("stage=build_prompt") == 1
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log


def test_configured_logging_writes_sanitised_diagnostics(app_boundary, tmp_path, capsys):
    # Default level (no LOG_LEVEL=DEBUG): sanitised, no traceback, no secrets.
    assert main.logging_setup.setup_logging() is True
    app_boundary.side_effect = TimeoutError("PRIVATE_EXCEPTION")
    with pytest.raises(RuntimeError):
        ai_manager.call_api("PRIVATE_PROMPT")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "WARNING" in log and "stage=call_api" in log and "timed out" in log
    assert "PRIVATE_" not in log and "fictional-integration-key" not in log
    assert "Traceback" not in log
    assert capsys.readouterr().err == ""


def test_unwritable_log_destination_keeps_menu_available(app_boundary, tmp_path, monkeypatch):
    # A file named "logs" makes os.makedirs("logs") fail, so the file log can't
    # open - the app must still run and warn about logging being unavailable.
    (tmp_path / "logs").write_text("not a directory")
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(return_value="5"))

    main.main()

    main.io_manager.main_menu.assert_called_once()
    messages = [call.args[0] for call in main.io_manager.show_message.call_args_list]
    assert any("logging" in message.lower() for message in messages)
    assert messages[-1] == "Bye!"
    app_boundary.assert_not_called()


def test_failed_log_write_does_not_crash_or_leak(app_boundary, monkeypatch, capsys):
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
    app_boundary.side_effect = TimeoutError("PRIVATE_PROVIDER_ERROR")

    with pytest.raises(RuntimeError, match="timed out"):
        ai_manager.call_api("PRIVATE_PROMPT")

    captured = capsys.readouterr()
    assert "PRIVATE_" not in captured.out and "PRIVATE_" not in captured.err


@pytest.mark.parametrize("failure", ["missing-findings", "detail-type", "invented-contact"])
def test_combined_validation_failure_stops_before_logic_and_storage(
    app_boundary, monkeypatch, failure,
):
    data = _findings()
    if failure == "missing-findings":
        data = _details()
    elif failure == "detail-type":
        data["details"]["emails"] = "PRIVATE_VALUE"
    else:
        data["details"]["emails"] = ["fictional@example.test"]
    _completed_reply(app_boundary, data)
    record = _record()
    original = record.copy()
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))
    evaluate, save = Mock(), Mock()
    monkeypatch.setattr(main.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(main.data_manager, "save", save)

    main.check_message()

    evaluate.assert_not_called()
    save.assert_not_called()
    main.io_manager.display_result.assert_not_called()
    main.io_manager.show_message.assert_called_once()
    assert "PRIVATE_" not in main.io_manager.show_message.call_args.args[0]
    assert app_boundary.call_count == 1
    assert record == original


def test_combined_caller_passes_validated_findings_to_logic_once(app_boundary, monkeypatch):
    record = _record()
    data = _findings()
    record["message"] += "; contact fictional@example.test."
    data["details"]["emails"] = ["fictional@example.test"]
    _completed_reply(app_boundary, data)
    # Any attempted second read would fail; no formatting request is needed.
    app_boundary.return_value.__enter__.return_value.read.side_effect = [
        app_boundary.return_value.__enter__.return_value.read.return_value,
        AssertionError("Unexpected second API response"),
    ]
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))
    result = {"score": 90, "priority": "HIGH", "reasons": [], "checklist": []}
    evaluate = Mock(return_value=result)
    save = Mock()
    monkeypatch.setattr(main.logic_manager, "evaluate", evaluate)
    monkeypatch.setattr(main.data_manager, "save", save)

    main.check_message()

    evaluate.assert_called_once_with({**record, "ai": data})
    assert "ai" not in record
    save.assert_called_once()
    assert save.call_args.args[0] == {
        "schema_version": 2, "channel": record["channel"],
        "message": record["message"], "result": result,
    }
    main.io_manager.display_result.assert_called_once_with(result)
    app_boundary.assert_called_once()


def test_combined_caller_uses_ai_findings_for_the_same_unexposed_input(app_boundary, monkeypatch):
    record = _record()
    record["submitted_category"] = None
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))
    for suspicious, credential, expected in ((False, False, 10), (True, True, 60)):
        data = _findings()
        data.update(suspicious=suspicious, credential_request=credential)
        _completed_reply(app_boundary, data)
        main.check_message()
        assert main.io_manager.display_result.call_args.args[0]["score"] == expected
    assert app_boundary.call_count == 2  # two records, one request each
    assert len(data_manager.load()) == 2



def test_configured_storage_logging_uses_application_file(
    app_boundary, tmp_path, monkeypatch
):
    (tmp_path / "reports.json").write_text('{PRIVATE_BROKEN')
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(return_value="5"))
    main.main()
    text = (tmp_path / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "data_manager" in text and "Could not read local report history" in text
    # Default (non-debug) logging must not leak the broken file contents.
    assert "PRIVATE" not in text
    # The corrupt history must be preserved, never overwritten.
    assert (tmp_path / "reports.json").read_text() == '{PRIVATE_BROKEN'


def test_recovered_timeout_saves_and_displays_only_one_assessment(app_boundary, monkeypatch):
    record = _record()
    _successful_reply(app_boundary)
    app_boundary.side_effect = [TimeoutError("PRIVATE_ERROR"), app_boundary.return_value]
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=record))

    main.check_message()

    assert app_boundary.call_count == 2
    saved = data_manager.load()
    assert len(saved) == 1
    assert saved[0] == {"schema_version": 2, "channel": record["channel"],
                        "message": record["message"],
                        "result": main.io_manager.display_result.call_args.args[0]}
    main.io_manager.display_result.assert_called_once()
    main.io_manager.show_message.assert_not_called()


def test_timeout_fallback_reaches_real_logic_and_saves_once(app_boundary, monkeypatch):
    monkeypatch.setenv("GROQ_FALLBACK_MODEL", "fictional/faster")
    _successful_reply(app_boundary)
    app_boundary.side_effect = [TimeoutError(), app_boundary.return_value]
    monkeypatch.setattr(main.io_manager, "collect_input", Mock(return_value=_record()))

    main.check_message()

    assert app_boundary.call_count == 2
    assert json.loads(app_boundary.call_args.args[0].data)["model"] == "fictional/faster"
    saved = data_manager.load()
    assert saved == [{"schema_version": 2, "channel": _record()["channel"],
                      "message": _record()["message"],
                      "result": main.io_manager.display_result.call_args.args[0]}]
    main.io_manager.display_result.assert_called_once()
    main.io_manager.show_message.assert_not_called()


@pytest.mark.parametrize("choice, handler_name", [("3", "upload_file"), ("4", "view_reports")])
def test_menu_routes_upload_and_saved_reports(app_boundary, monkeypatch, choice, handler_name):
    handler = Mock()
    monkeypatch.setattr(main, handler_name, handler)
    monkeypatch.setattr(main.io_manager, "main_menu", Mock(side_effect=[choice, "5"]))

    main.main()

    handler.assert_called_once_with()
    app_boundary.assert_not_called()
