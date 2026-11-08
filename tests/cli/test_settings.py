"""Environment loading and runtime settings."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from phishreport.cli import main
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.local_settings import LocalSettings
from phishreport.logging_setup import AppLogging

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"
io_manager = IOManager(ConsoleTerminal())


# ============================================================================
# Env Loading
# ============================================================================
@pytest.fixture
def env_loading_env_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("PHISHREPORT_TEST_NEW", "PHISHREPORT_TEST_EXISTING"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    return tmp_path / ".env"


def test_env_loading_missing_env_is_optional(env_loading_env_folder):
    assert main.EnvLoader().load() is True


@pytest.mark.parametrize("content", [b"", b"# comment\n\n", b"ignored line without assignment\n"])
def test_env_loading_empty_or_ignored_env_is_optional(env_loading_env_folder, content):
    env_loading_env_folder.write_bytes(content)
    assert main.EnvLoader().load() is True
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_env_loading_valid_env_preserves_existing_and_first_assignment(
    env_loading_env_folder, monkeypatch, encoding
):
    monkeypatch.setenv("PHISHREPORT_TEST_EXISTING", "supplied-by-shell")
    env_loading_env_folder.write_text(
        "# comment\n PHISHREPORT_TEST_EXISTING = from-file\n"
        "PHISHREPORT_TEST_NEW = caf\u00e9=value\nPHISHREPORT_TEST_NEW=second-value\n",
        encoding=encoding,
    )
    assert main.EnvLoader().load() is True
    assert os.environ["PHISHREPORT_TEST_EXISTING"] == "supplied-by-shell"
    assert os.environ["PHISHREPORT_TEST_NEW"] == "caf\u00e9=value"


def test_env_loading_directory_env_does_not_crash(env_loading_env_folder):
    env_loading_env_folder.mkdir()
    assert main.EnvLoader().load() is False


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_env_loading_unreadable_env_does_not_crash(env_loading_env_folder, monkeypatch, error):
    env_loading_env_folder.write_text("PHISHREPORT_TEST_NEW=private-value\n")
    monkeypatch.setattr("builtins.open", Mock(side_effect=error("PRIVATE_CONFIG_SENTINEL")))
    assert main.EnvLoader().load() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize(
    "prefix",
    [
        b"",
        b"PHISHREPORT_TEST_NEW=private-value\n" + b"# padding\n" * 1000,
    ],
    ids=["invalid-first-byte", "invalid-after-valid-lines"],
)
def test_env_loading_invalid_utf8_env_is_rejected_without_partial_settings(
    env_loading_env_folder, prefix
):
    env_loading_env_folder.write_bytes(prefix + b"\xff\n")
    assert main.EnvLoader().load() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize("invalid", ["=value", "BAD\x00KEY=value", "BAD=value\x00suffix"])
def test_env_loading_invalid_assignment_is_rejected_without_partial_settings(
    env_loading_env_folder, invalid
):
    env_loading_env_folder.write_text(
        "PHISHREPORT_TEST_NEW=private-value\n" + invalid, encoding="utf-8"
    )
    assert main.EnvLoader().load() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


def test_env_loading_interrupted_read_does_not_apply_earlier_lines(
    env_loading_env_folder, monkeypatch
):
    def interrupted():
        yield "PHISHREPORT_TEST_NEW=private-value\n"
        raise OSError("PRIVATE_CONFIG_SENTINEL")

    opened = MagicMock()
    opened.return_value.__enter__.return_value.__iter__.side_effect = interrupted
    monkeypatch.setattr("builtins.open", opened)
    assert main.EnvLoader().load() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.fixture
def env_loading_startup(cli, monkeypatch):
    setup = Mock(return_value=True)
    menu = Mock(return_value="6")
    notice = Mock()
    monkeypatch.setattr(AppLogging, "setup", setup)
    monkeypatch.setattr(cli.app, "load_reports", Mock(return_value=[]))
    monkeypatch.setattr(cli.io_manager, "main_menu", menu)
    monkeypatch.setattr(cli.io_manager, "show_message", notice)
    return setup, menu, notice


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG], ids=["info", "debug"])
@pytest.mark.parametrize("failure", ["directory", "invalid-utf8", "invalid-assignment"])
def test_env_loading_bad_env_warns_safely_and_reaches_menu(
    cli, env_loading_env_folder, env_loading_startup, monkeypatch, caplog, level, failure
):
    monkeypatch.setenv("PHISHREPORT_TEST_EXISTING", "supplied-by-shell")
    if failure == "directory":
        env_loading_env_folder.mkdir()
    elif failure == "invalid-utf8":
        env_loading_env_folder.write_bytes(b"PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n\xff")
    else:
        env_loading_env_folder.write_text("PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n=value")
    caplog.set_level(level, logger=main.__name__)

    cli.app.run()

    setup, menu, notice = env_loading_startup
    setup.assert_called_once_with()
    menu.assert_called_once_with()
    messages = [call.args[0] for call in notice.call_args_list]
    assert sum(".env could not be loaded" in message for message in messages) == 1
    assert "Bye!" in messages
    assert os.environ["PHISHREPORT_TEST_EXISTING"] == "supplied-by-shell"
    assert "PHISHREPORT_TEST_NEW" not in os.environ
    assert "PRIVATE_CONFIG_SENTINEL" not in caplog.text + "\n".join(messages)
    warnings = [record for record in caplog.records if ".env" in record.message]
    assert len(warnings) == 1 and warnings[0].exc_info is None


def test_env_loading_valid_env_is_loaded_before_logging_without_warning(
    cli, env_loading_env_folder, env_loading_startup, monkeypatch
):
    env_loading_env_folder.write_text("PHISHREPORT_TEST_NEW=from-file", encoding="utf-8")
    setup, menu, notice = env_loading_startup
    setup.side_effect = lambda: os.environ["PHISHREPORT_TEST_NEW"] == "from-file"

    cli.app.run()

    menu.assert_called_once_with()
    assert not any("Warning:" in call.args[0] for call in notice.call_args_list)


def test_env_loading_missing_env_reaches_menu_without_configuration_warning(
    cli, env_loading_env_folder, env_loading_startup
):
    cli.app.run()
    env_loading_startup[1].assert_called_once_with()
    assert not any(".env" in call.args[0] for call in env_loading_startup[2].call_args_list)


def test_env_loading_bad_env_warning_survives_unavailable_logging(
    cli, env_loading_env_folder, env_loading_startup
):
    env_loading_env_folder.mkdir()
    env_loading_startup[0].return_value = False

    cli.app.run()

    messages = [call.args[0] for call in env_loading_startup[2].call_args_list]
    assert "Warning: diagnostic logging is unavailable." in messages
    assert sum(".env could not be loaded" in message for message in messages) == 1
    env_loading_startup[1].assert_called_once_with()


@pytest.mark.parametrize("failure", ["directory", "invalid-utf8"])
@pytest.mark.parametrize("answers", ["6\n", ""], ids=["quit", "eof"])
def test_env_loading_actual_cli_reaches_menu_after_configuration_failure(
    env_loading_env_folder, failure, answers
):
    if failure == "directory":
        env_loading_env_folder.mkdir()
    else:
        env_loading_env_folder.write_bytes(b"PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n\xff")
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    for key in ("DATABASE_URL", "GROQ_API_KEY", "GROQ_FALLBACK_MODEL"):
        environment.pop(key, None)
    environment["LOG_LEVEL"] = "INFO"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONPATH"] = str(root) + os.pathsep + environment.get("PYTHONPATH", "")
    run = subprocess.run(
        [sys.executable, "-m", "phishreport.cli"],
        input=answers,
        text=True,
        capture_output=True,
        encoding="utf-8",
        env=environment,
        cwd=env_loading_env_folder.parent,
        timeout=10,
    )
    assert run.returncode == 0
    assert "=== PhishReport ===" in run.stdout
    assert run.stdout.count("Warning: .env could not be loaded") == 1
    assert ("Bye!" if answers else "Interrupted. Goodbye!") in run.stdout
    assert "Traceback" not in run.stderr
    logs = (env_loading_env_folder.parent / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "PRIVATE_CONFIG_SENTINEL" not in run.stdout + run.stderr + logs


# ============================================================================
# Runtime Settings
# ============================================================================
@pytest.mark.parametrize("saved_folder", [[], {}, 7, True])
def test_runtime_settings_invalid_saved_folder_reprompts_without_crashing(
    tmp_path, monkeypatch, saved_folder
):
    monkeypatch.chdir(tmp_path)
    settings = tmp_path / ".phishreport_config.json"
    settings.write_text(json.dumps({"eml_folder": saved_folder}), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: str(tmp_path))
    assert io_manager.folder_picker.get_eml_folder() == str(tmp_path)
    assert json.loads(settings.read_text())["eml_folder"] == str(tmp_path)


@pytest.mark.parametrize("payload", [[], None])
def test_runtime_settings_non_object_settings_are_logged_and_recovered(
    tmp_path, monkeypatch, caplog, payload
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".phishreport_config.json").write_text(json.dumps(payload), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="phishreport.local_settings"):
        assert LocalSettings().load() == {}
    assert "Could not read local config" in caplog.text


@pytest.mark.parametrize("level", ["BASIC_FORMAT", "_STYLES"])
def test_runtime_settings_logging_attribute_names_do_not_crash_startup(tmp_path, level):
    """An environment value must be a level, not any attribute of logging."""
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ, LOG_LEVEL=level, PYTHONPATH=str(root))
    environment.pop("GROQ_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-m", "phishreport.cli"],
        cwd=tmp_path,
        input="6\n",
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Bye!" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("invalid_choice", ["Â²", "9" * 5000])
def test_runtime_settings_email_picker_rejects_unusable_numeric_choices(
    tmp_path, monkeypatch, invalid_choice
):
    folder = tmp_path
    source = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample-1.eml"
    (folder / source.name).write_bytes(source.read_bytes())
    answers = iter([invalid_choice, "c"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert io_manager.folder_picker.choose_eml_file(folder) is None


def test_runtime_settings_unreadable_email_folder_returns_safely_to_menu(monkeypatch, capsys):
    folder = Path(__file__).resolve().parents[2] / "emails"
    picker = io_manager.folder_picker
    monkeypatch.setattr(picker, "get_eml_folder", lambda: folder)

    def cannot_list(_folder):
        raise PermissionError("PRIVATE_PATH")

    monkeypatch.setattr(picker, "list_eml_files", cannot_list)
    assert io_manager.folder_picker.get_eml_from_folder() is None
    output = capsys.readouterr().out
    assert "Unable to list" in output
    assert "PRIVATE_PATH" not in output
