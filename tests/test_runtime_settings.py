"""Regression checks for persisted preferences and startup logging configuration."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import io_manager
import local_settings
import pytest


@pytest.mark.parametrize("saved_folder", [[], {}, 7, True])
def test_invalid_saved_folder_reprompts_without_crashing(tmp_path, monkeypatch, saved_folder):
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".phishreport_config.json"
    settings.write_text(json.dumps({"eml_folder": saved_folder}), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: str(tmp_path))
    assert io_manager.get_eml_folder() == str(tmp_path)
    assert json.loads(settings.read_text())["eml_folder"] == str(tmp_path)


@pytest.mark.parametrize("payload", [[], None])
def test_non_object_settings_are_logged_and_recovered(tmp_path, monkeypatch, caplog, payload):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".phishreport_config.json").write_text(json.dumps(payload), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="local_settings"):
        assert local_settings.load_settings() == {}
    assert "Could not read local config" in caplog.text


@pytest.mark.parametrize("level", ["BASIC_FORMAT", "_STYLES"])
def test_logging_attribute_names_do_not_crash_startup(tmp_path, level):
    """An environment value must be a level, not any attribute of logging."""
    app = Path(__file__).resolve().parents[1] / "app"
    environment = dict(os.environ, LOG_LEVEL=level)
    environment.pop("GROQ_API_KEY", None)
    result = subprocess.run(
        [sys.executable, str(app / "main.py")], cwd=tmp_path,
        input="5\n", text=True, capture_output=True, env=environment, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Bye!" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("invalid_choice", ["Â²", "9" * 5000])
def test_email_picker_rejects_unusable_numeric_choices(tmp_path, monkeypatch, invalid_choice):
    folder = tmp_path
    source = Path(__file__).resolve().parents[1] / "emails" / "sample-1.eml"
    (folder / source.name).write_bytes(source.read_bytes())
    answers = iter([invalid_choice, "c"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert io_manager.choose_eml_file(folder) is None


def test_unreadable_email_folder_returns_safely_to_menu(monkeypatch, capsys):
    folder = Path(__file__).resolve().parents[1] / "emails"
    monkeypatch.setattr(io_manager, "get_eml_folder", lambda: folder)

    def cannot_list(_folder):
        raise PermissionError("PRIVATE_PATH")

    monkeypatch.setattr(io_manager, "list_eml_files", cannot_list)
    assert io_manager.get_eml_from_folder() is None
    output = capsys.readouterr().out
    assert "Unable to list" in output
    assert "PRIVATE_PATH" not in output
