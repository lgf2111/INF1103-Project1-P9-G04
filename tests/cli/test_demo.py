"""Automated feature showcase: run with -m demo."""

import http.client
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import phishreport
from phishreport import local_settings
from phishreport.ai import groq_client
from phishreport.cli import web_upload
from phishreport.data import DataManager, json_storage
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"
io_manager = IOManager(ConsoleTerminal())


# ============================================================================
# Demo
# ============================================================================
@pytest.fixture
def demo_transport(tmp_path, monkeypatch):
    """Only provider transport is replaced; input, validation, logic and save are real."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "unused-offline-demo")
    monkeypatch.setenv("GROQ_MODEL", "offline/demo")
    monkeypatch.setenv("GROQ_MAX_ATTEMPTS", "1")
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)
    transport = MagicMock()
    monkeypatch.setattr(groq_client.urllib.request, "urlopen", transport)
    return transport


def demo_reply(transport, **changes):
    findings = {
        "credential_request": True,
        "suspicious": True,
        "insufficient_context": False,
        "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
    }
    findings.update(changes)
    envelope = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(findings),
                },
            }
        ]
    }
    transport.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()


@pytest.mark.demo
@pytest.mark.parametrize(
    "entry, name",
    [
        pytest.param("manual", "sample-1.eml", id="manual-real-email"),
        pytest.param("folder", "sample-2.eml", id="folder-real-email"),
        pytest.param("browser", "sample-3.eml", id="browser-real-email"),
    ],
)
def test_demo_real_email_pipeline_and_reload(
    cli, demo_transport, monkeypatch, tmp_path, capsys, name, entry
):
    path = REAL_EMAILS / name
    sender, message = io_manager.eml_reader.read_path(path)
    demo_reply(demo_transport)
    if entry == "manual":
        answers = iter(["Email", sender, message, "no", "no", "no"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        cli.app.check_message()
    elif entry == "folder":
        local_settings.save_setting("eml_folder", str(REAL_EMAILS))
        files = io_manager.folder_picker.list_eml_files(REAL_EMAILS)
        answers = iter([str(files.index(path) + 1), "no", "no", "no"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        cli.app.check_message(io_manager.collect_input_from_folder())
    else:
        monkeypatch.setattr(
            web_upload,
            "start_and_wait_for_upload",
            lambda: {
                "filename": name,
                "content": path.read_bytes(),
            },
        )
        answers = iter(["no", "no", "no"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        cli.app.upload_file()

    records = DataManager().load(strict=True)
    assert len(records) == 1
    assert records[0]["message"] == message
    assert records[0]["result"]["score"] == 60
    assert records[0]["result"]["priority"] == "MEDIUM"
    assert records[0]["result"]["reasons"] and records[0]["result"]["checklist"]
    assert "Rule-based score: 60" in capsys.readouterr().out
    demo_transport.assert_called_once()
    before = (tmp_path / "reports.json").read_bytes()
    # A separate interpreter proves reload does not depend on in-memory state.
    environment = dict(os.environ, PYTHONPATH=str(Path(phishreport.__file__).resolve().parents[1]))
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from phishreport.data import DataManager; "
            "assert DataManager().load(strict=True)[0]['result']['score'] == 60",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert (tmp_path / "reports.json").read_bytes() == before


@pytest.mark.demo
@pytest.mark.parametrize(
    "changes, actions, score",
    [
        ({"suspicious": False, "credential_request": False}, ["no", "no", "no"], 10),
        (
            {"suspicious": False, "credential_request": False, "insufficient_context": True},
            ["no", "no", "no"],
            20,
        ),
        ({}, ["yes", "untrusted link reported", "yes", "reported file", "yes", "yes", "no"], 80),
        ({"suspicious": False, "credential_request": False}, ["no", "no", "password"], 90),
        ({"suspicious": False, "credential_request": False}, ["no", "no", "otp"], 90),
    ],
    ids=[
        "normal-findings",
        "uncertain-findings",
        "click-and-download",
        "password-disclosure",
        "otp-disclosure",
    ],
)
def test_demo_exposure_and_uncertainty(cli, demo_transport, monkeypatch, changes, actions, score):
    demo_reply(demo_transport, **changes)
    answers = iter(actions)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.app.check_message(
        io_manager.collect_input_from_upload(
            {
                "filename": "sample-1.eml",
                "content": (REAL_EMAILS / "sample-1.eml").read_bytes(),
            }
        )
    )
    result = DataManager().load(strict=True)[0]["result"]
    assert result["score"] == score
    assert result["reasons"] and result["checklist"]
    demo_transport.assert_called_once()


@pytest.mark.demo
@pytest.mark.parametrize(
    "failure",
    ["timeout", "invalid-ai", "save"],
    ids=["AI-timeout-no-assessment", "invalid-AI-no-assessment", "valid-assessment-save-failure"],
)
def test_demo_failed_ai_differs_from_failed_save(cli, demo_transport, monkeypatch, capsys, failure):
    demo_reply(demo_transport)
    if failure == "timeout":
        demo_transport.side_effect = TimeoutError("Private transport detail")
    elif failure == "invalid-ai":
        demo_transport.return_value.__enter__.return_value.read.return_value = b'{"choices":[]}'
    else:
        monkeypatch.setattr(json_storage.os, "replace", Mock(side_effect=PermissionError()))
    answers = iter(["no", "no", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.app.check_message(
        io_manager.collect_input_from_upload(
            {
                "filename": "sample-2.eml",
                "content": (REAL_EMAILS / "sample-2.eml").read_bytes(),
            }
        )
    )
    output = capsys.readouterr().out
    assert DataManager().load() == []
    assert "Private transport detail" not in output
    if failure == "save":
        assert "Could not save" in output and "Rule-based score: 60" in output
    else:
        assert "check failed" in output and "=== Assessment ===" not in output


@pytest.mark.demo
def test_demo_actual_http_upload_of_real_email(cli, demo_transport, monkeypatch):
    """Real local HTTP server and upload, mocked external provider only."""
    demo_reply(demo_transport)
    ready = threading.Event()
    servers, errors = [], []
    original = web_upload._UploadServer

    def make_server(address):
        server = original(address)
        servers.append(server)
        ready.set()
        return server

    def run():
        try:
            cli.app.upload_file()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(web_upload, "BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(web_upload, "PORT", 0)
    monkeypatch.setattr(web_upload, "_UploadServer", make_server)
    answers = iter(["no", "no", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert ready.wait(5)
    raw = (REAL_EMAILS / "sample-3.eml").read_bytes()
    body = (
        b'--demo\r\nContent-Disposition: form-data; name="file"; filename="sample-3.eml"'
        b"\r\nContent-Type: message/rfc822\r\n\r\n" + raw + b"\r\n--demo--\r\n"
    )
    connection = http.client.HTTPConnection("127.0.0.1", servers[0].server_port, timeout=5)
    try:
        connection.request(
            "POST", "/", body=body, headers={"Content-Type": "multipart/form-data; boundary=demo"}
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
    finally:
        connection.close()
    worker.join(5)
    assert not worker.is_alive() and not errors
    saved = DataManager().load(strict=True)[0]
    assert saved["result"]["score"] == 60
    assert saved["message"] == io_manager.eml_reader.read_bytes(raw)[1]
    assert servers[0].socket.fileno() == -1
