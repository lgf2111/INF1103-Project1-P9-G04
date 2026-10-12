"""Optional startup configuration must not crash or partly replace settings."""
import os
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
