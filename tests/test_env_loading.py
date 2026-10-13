"""Optional startup configuration must not crash or partly replace settings."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import main
import pytest


@pytest.fixture
def env_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key in ("PHISHREPORT_TEST_NEW", "PHISHREPORT_TEST_EXISTING"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    return tmp_path / ".env"


def test_missing_env_is_optional(env_folder):
    assert main.load_env() is True


@pytest.mark.parametrize("content", [b"", b"# comment\n\n", b"ignored line without assignment\n"])
def test_empty_or_ignored_env_is_optional(env_folder, content):
    env_folder.write_bytes(content)
    assert main.load_env() is True
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_valid_env_preserves_existing_and_first_assignment(env_folder, monkeypatch, encoding):
    monkeypatch.setenv("PHISHREPORT_TEST_EXISTING", "supplied-by-shell")
    env_folder.write_text(
        "# comment\n PHISHREPORT_TEST_EXISTING = from-file\n"
        "PHISHREPORT_TEST_NEW = caf\u00e9=value\nPHISHREPORT_TEST_NEW=second-value\n",
        encoding=encoding,
    )
    assert main.load_env() is True
    assert os.environ["PHISHREPORT_TEST_EXISTING"] == "supplied-by-shell"
    assert os.environ["PHISHREPORT_TEST_NEW"] == "caf\u00e9=value"


def test_directory_env_does_not_crash(env_folder):
    env_folder.mkdir()
    assert main.load_env() is False


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_unreadable_env_does_not_crash(env_folder, monkeypatch, error):
    env_folder.write_text("PHISHREPORT_TEST_NEW=private-value\n")
    monkeypatch.setattr("builtins.open", Mock(side_effect=error("PRIVATE_CONFIG_SENTINEL")))
    assert main.load_env() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize("prefix", [
    b"", b"PHISHREPORT_TEST_NEW=private-value\n" + b"# padding\n" * 1000,
], ids=["invalid-first-byte", "invalid-after-valid-lines"])
def test_invalid_utf8_env_is_rejected_without_partial_settings(env_folder, prefix):
    env_folder.write_bytes(prefix + b"\xff\n")
    assert main.load_env() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.mark.parametrize("invalid", ["=value", "BAD\x00KEY=value", "BAD=value\x00suffix"])
def test_invalid_assignment_is_rejected_without_partial_settings(env_folder, invalid):
    env_folder.write_text("PHISHREPORT_TEST_NEW=private-value\n" + invalid, encoding="utf-8")
    assert main.load_env() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


def test_interrupted_read_does_not_apply_earlier_lines(env_folder, monkeypatch):
    def interrupted():
        yield "PHISHREPORT_TEST_NEW=private-value\n"
        raise OSError("PRIVATE_CONFIG_SENTINEL")

    opened = MagicMock()
    opened.return_value.__enter__.return_value.__iter__.side_effect = interrupted
    monkeypatch.setattr("builtins.open", opened)
    assert main.load_env() is False
    assert "PHISHREPORT_TEST_NEW" not in os.environ


@pytest.fixture
def startup(monkeypatch):
    setup = Mock(return_value=True)
    menu = Mock(return_value="5")
    notice = Mock()
    monkeypatch.setattr(main.logging_setup, "setup_logging", setup)
    monkeypatch.setattr(main, "load_reports", Mock(return_value=[]))
    monkeypatch.setattr(main.io_manager, "main_menu", menu)
    monkeypatch.setattr(main.io_manager, "show_message", notice)
    return setup, menu, notice


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG], ids=["info", "debug"])
@pytest.mark.parametrize("failure", ["directory", "invalid-utf8", "invalid-assignment"])
def test_bad_env_warns_safely_and_reaches_menu(env_folder, startup, monkeypatch, caplog,
                                            level, failure):
    monkeypatch.setenv("PHISHREPORT_TEST_EXISTING", "supplied-by-shell")
    if failure == "directory":
        env_folder.mkdir()
    elif failure == "invalid-utf8":
        env_folder.write_bytes(b"PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n\xff")
    else:
        env_folder.write_text("PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n=value")
    caplog.set_level(level, logger=main.__name__)

    main.main()

    setup, menu, notice = startup
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


def test_valid_env_is_loaded_before_logging_without_warning(env_folder, startup, monkeypatch):
    env_folder.write_text("PHISHREPORT_TEST_NEW=from-file", encoding="utf-8")
    setup, menu, notice = startup
    setup.side_effect = lambda: os.environ["PHISHREPORT_TEST_NEW"] == "from-file"

    main.main()

    menu.assert_called_once_with()
    assert not any("Warning:" in call.args[0] for call in notice.call_args_list)


def test_missing_env_reaches_menu_without_configuration_warning(env_folder, startup):
    main.main()
    startup[1].assert_called_once_with()
    assert not any(".env" in call.args[0] for call in startup[2].call_args_list)


def test_bad_env_warning_survives_unavailable_logging(env_folder, startup):
    env_folder.mkdir()
    startup[0].return_value = False

    main.main()

    messages = [call.args[0] for call in startup[2].call_args_list]
    assert "Warning: diagnostic logging is unavailable." in messages
    assert sum(".env could not be loaded" in message for message in messages) == 1
    startup[1].assert_called_once_with()


@pytest.mark.parametrize("failure", ["directory", "invalid-utf8"])
@pytest.mark.parametrize("answers", ["5\n", ""], ids=["quit", "eof"])
def test_actual_cli_reaches_menu_after_configuration_failure(env_folder, failure, answers):
    if failure == "directory":
        env_folder.mkdir()
    else:
        env_folder.write_bytes(b"PHISHREPORT_TEST_NEW=PRIVATE_CONFIG_SENTINEL\n\xff")
    app = Path(__file__).resolve().parents[1] / "app"
    environment = os.environ.copy()
    for key in ("DATABASE_URL", "GROQ_API_KEY", "GROQ_FALLBACK_MODEL"):
        environment.pop(key, None)
    environment["LOG_LEVEL"] = "INFO"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONPATH"] = str(app) + os.pathsep + environment.get("PYTHONPATH", "")
    run = subprocess.run(
        [sys.executable, str(app / "main.py")], input=answers, text=True,
        capture_output=True, encoding="utf-8", env=environment, cwd=env_folder.parent,
        timeout=10,
    )
    assert run.returncode == 0
    assert "=== PhishReport ===" in run.stdout
    assert run.stdout.count("Warning: .env could not be loaded") == 1
    assert ("Bye!" if answers else "Interrupted. Goodbye!") in run.stdout
    assert "Traceback" not in run.stderr
    logs = (env_folder.parent / "logs" / "phishreport.log").read_text(encoding="utf-8")
    assert "PRIVATE_CONFIG_SENTINEL" not in run.stdout + run.stderr + logs
