"""Input and output boundaries for submitted messages."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from phishreport import local_settings
from phishreport.ai import AIResponseValidator, groq_client
from phishreport.cli import main, web_upload
from phishreport.data import DataManager
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"
io_manager = IOManager(ConsoleTerminal())


# ============================================================================
# Submission Boundaries
# ============================================================================
validator = AIResponseValidator()


def submission_boundaries_deep_json():
    depth = sys.getrecursionlimit() * 3
    return "[" * depth + "0" + "]" * depth


def test_submission_boundaries_deep_ai_content_is_a_validation_failure():
    with pytest.raises(ValueError):
        validator.validate_response(
            validator.parse_response('{"details":' + submission_boundaries_deep_json() + "}")
        )


def test_submission_boundaries_deep_provider_envelope_fails_without_an_assessment(
    cli, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "unused-offline")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = submission_boundaries_deep_json().encode()
    monkeypatch.setattr(groq_client.urllib.request, "urlopen", Mock(return_value=response))
    save, display = Mock(), Mock()
    monkeypatch.setattr(cli.data_manager, "save", save)
    monkeypatch.setattr(cli.io_manager, "display_result", display)
    cli.app.check_message({"message": "Malformed response boundary"})
    save.assert_not_called()
    display.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        '[{"score":NaN}]',
        '[{"score":Infinity}]',
        '[{"score":1e999}]',
        '[{"message":"original","message":"replacement"}]',
    ],
)
def test_submission_boundaries_invalid_history_is_preserved_and_cannot_be_appended(
    tmp_path, monkeypatch, payload
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "reports.json"
    path.write_text(payload, encoding="utf-8")
    before = path.read_bytes()
    assert DataManager().load() == []
    with pytest.raises(ValueError):
        DataManager().load(strict=True)
    report = {
        "schema_version": 2,
        "channel": "email",
        "message": "Existing record",
        "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
    }
    with pytest.raises(ValueError):
        DataManager().save(report)
    assert path.read_bytes() == before


def test_submission_boundaries_deep_history_keeps_startup_and_history_menu_usable(
    cli, tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "reports.json"
    path.write_text(submission_boundaries_deep_json(), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(main.logging_setup, "setup_logging", lambda: True)
    choices = iter(["4", "5"])
    monkeypatch.setattr(cli.io_manager, "main_menu", lambda: next(choices))
    cli.app.run()
    assert "Bye!" in capsys.readouterr().out
    assert path.read_bytes() == before


@pytest.mark.parametrize("port", [-1, 65536])
def test_submission_boundaries_upload_invalid_port_returns_to_menu(cli, monkeypatch, port, capsys):
    monkeypatch.setattr(web_upload, "PORT", port)
    cli.app.upload_file()
    assert "Upload failed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload", [b"{broken", b"[]", b"\xff", b'{"eml_folder":"one","eml_folder":"two"}']
)
def test_submission_boundaries_settings_save_preserves_corrupt_file(tmp_path, monkeypatch, payload):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".phishreport_config.json"
    path.write_bytes(payload)
    assert local_settings.save_setting("eml_folder", str(tmp_path)) is False
    assert path.read_bytes() == payload


def test_submission_boundaries_settings_write_failure_preserves_existing_values(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".phishreport_config.json"
    path.write_text('{"other":"keep"}', encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(local_settings.os, "replace", Mock(side_effect=PermissionError("PRIVATE")))
    assert local_settings.save_setting("eml_folder", str(tmp_path)) is False
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_submission_boundaries_folder_can_be_used_when_preference_cannot_be_saved(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".phishreport_config.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: str(tmp_path))
    assert io_manager.folder_picker.get_eml_folder() == str(tmp_path)
    text = capsys.readouterr().out
    assert "Could not save" in text
    assert "Saved. You won't" not in text
    assert path.read_text() == "{broken"


def test_submission_boundaries_valid_settings_save_retains_unrelated_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".phishreport_config.json"
    path.write_text('{"other":"keep"}', encoding="utf-8")
    assert local_settings.save_setting("eml_folder", str(tmp_path)) is True
    assert json.loads(path.read_text()) == {"other": "keep", "eml_folder": str(tmp_path)}
