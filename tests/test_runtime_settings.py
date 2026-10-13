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
