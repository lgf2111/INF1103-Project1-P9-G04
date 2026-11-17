"""Post-verdict exposure checklist: TTY checkbox, numbered fallback, re-score."""

import io
import os
import pty
import re
import termios
import threading
from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager
from phishreport.io.exposure_screen import ExposureScreen, build_exposure
from phishreport.logic import LogicManager

FINDINGS = {
    "credential_request": True,
    "suspicious": True,
    "insufficient_context": False,
    "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
}


def record(message="A fictional message asks for a password."):
    """Return the complete record built by the CLI input routes."""
    return {
        "channel": "chat",
        "sender": None,
        "message": message,
        "has_link": True,
        "link": "https://example.test/login",
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
        "disclosure_answered": False,
    }


class FakeTTY:
    """Minimal stdin surface for the raw-mode screen."""

    def __init__(self, descriptor):
        self.descriptor = descriptor

    def isatty(self):
        return True

    def fileno(self):
        return self.descriptor


class DrawnOutput(io.StringIO):
    """Signal when the complete screen has been drawn."""

    def __init__(self):
        super().__init__()
        self.drawn = threading.Event()

    def write(self, text):
        written = super().write(text)
        if "Entered a one-time code" in text:
            self.drawn.set()
        return written


def send_after_draw(master, keys, output):
    """Write keys once the screen is visible and raw mode is active."""

    def send():
        if not output.drawn.wait(5):
            return
        os.write(master, keys)

    worker = threading.Thread(target=send, daemon=True)
    worker.start()
    return worker


@pytest.fixture
def tty_pair():
    """Create a real pseudo-terminal and close both descriptors afterwards."""
    pairs = []

    def create(keys):
        master, slave = pty.openpty()
        output = DrawnOutput()
        worker = send_after_draw(master, keys, output)
        pairs.append((master, slave, worker))
        return master, slave, output

    yield create
    for master, slave, worker in pairs:
        worker.join(5)
        os.close(master)
        os.close(slave)


def build_app(tmp_path, stdin, stdout):
    """Compose the real CLI workflow with a stubbed AI service."""
    ai = Mock(**{"assess.return_value": dict(FINDINGS)})
    data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    terminal = Mock()
    manager = IOManager(terminal, stdin=stdin, stdout=stdout)
    app = PhishReportApp(manager, ai, LogicManager(), data)
    return app, ai, data, terminal


def test_tty_down_space_enter_clicked_rescores_the_same_saved_report(
    tmp_path, tty_pair,
):
    """Down, Space, Enter selects the first item and replaces the report."""
    master, slave, output = tty_pair(b"\x1b[B \r")
    original = termios.tcgetattr(slave)
    app, ai, data, terminal = build_app(tmp_path, FakeTTY(slave), output)
    save = Mock(wraps=data.save)
    data.save = save

    app.check_message(record())

    assert termios.tcgetattr(slave) == original
    assert save.call_count == 2
    plain, updated = (call.args[0] for call in save.call_args_list)
    assert "exposure" not in plain
    assert updated["assessment_id"] == plain["assessment_id"]
    assert updated["exposure"] == {
        "clicked": True,
        "downloaded": False,
        "submitted_category": None,
        "disclosure_answered": True,
    }
    assert updated["result"]["score"] == 80
    assert updated["result"]["priority"] == "HIGH"
    assert data.load(strict=True) == [updated]
    ai.assess.assert_called_once()

    screen = output.getvalue()
    assert screen.count("Anything you did with it?") == 1
    assert "  [ ] Clicked the link" in screen
    assert "\x1b[4A" in screen
    assert screen.endswith("\x1b[5A\r\x1b[J")
    assert ("Saved report updated.",) in [call.args for call in terminal.write.call_args_list]


def test_escape_keeps_the_saved_report_and_prints_nothing_new(tmp_path, tty_pair):
    """Escape skips the checklist without replacing or re-displaying anything."""
    master, slave, output = tty_pair(b"\x1b")
    original = termios.tcgetattr(slave)
    app, ai, data, terminal = build_app(tmp_path, FakeTTY(slave), output)
    save = Mock(wraps=data.save)
    data.save = save

    app.check_message(record())

    assert termios.tcgetattr(slave) == original
    assert save.call_count == 1
    assert "exposure" not in save.call_args.args[0]
    assert terminal.write.call_count
    assert ("Saved report updated.",) not in [
        call.args for call in terminal.write.call_args_list
    ]
    assert "updated" not in output.getvalue().lower()
    assert data.load(strict=True) == [save.call_args.args[0]]
    ai.assess.assert_called_once()


def test_non_tty_numbers_map_to_clicked_and_password_and_score_ninety(tmp_path):
    """Piped input keeps the plain numbered prompt and multi-select mapping."""
    ai = Mock(**{"assess.return_value": dict(FINDINGS)})
    data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    terminal = Mock()
    terminal.read.return_value = "1,3"
    app = PhishReportApp(IOManager(terminal), ai, LogicManager(), data)

    app.check_message(record())

    [saved] = data.load(strict=True)
    assert saved["exposure"] == {
        "clicked": True,
        "downloaded": False,
        "submitted_category": "password",
        "disclosure_answered": True,
    }
    assert saved["result"]["score"] == 90
    assert saved["result"]["priority"] == "HIGH"
    prompt = terminal.read.call_args.args[0]
    assert "1,3,4 + Enter, or Enter to skip" in prompt
    terminal.write.assert_any_call(
        "Anything you did with it? 1 clicked, 2 downloaded, 3 password, "
        "4 one-time code"
    )


def test_ctrl_c_restores_terminal_settings(tty_pair):
    """Ctrl-C interrupts the screen but never leaves the terminal in raw mode."""
    master, slave, output = tty_pair(b"\x03")
    original = termios.tcgetattr(slave)
    screen = ExposureScreen(FakeTTY(slave), output)

    with pytest.raises(KeyboardInterrupt):
        screen.run()

    assert termios.tcgetattr(slave) == original
    assert output.getvalue().endswith("\x1b[5A\r\x1b[J")


def test_password_and_otp_together_store_password_with_the_reason_in_code():
    """The single stored category picks password and the comment explains it."""
    exposure = build_exposure({"password", "otp"})

    assert exposure["submitted_category"] == "password"
    source = __import__("inspect").getsource(build_exposure)
    comment = "\n".join(
        line for line in source.splitlines() if line.strip().startswith("#")
    )
    assert "single" in comment.lower()
    assert "password" in comment.lower()


def test_numbered_prompt_reprompts_invalid_input():
    """The line-based fallback ignores bad answers until one is valid."""
    terminal = Mock()
    terminal.read.side_effect = ["password", "2,3"]

    exposure = IOManager(terminal).collect_exposure()

    assert exposure == {
        "clicked": False,
        "downloaded": True,
        "submitted_category": "password",
        "disclosure_answered": True,
    }
    assert terminal.read.call_count == 2


def test_empty_numbered_answer_skips_without_an_exposure_block():
    """Enter alone leaves the saved plain assessment alone."""
    terminal = Mock()
    terminal.read.return_value = ""

    assert IOManager(terminal).collect_exposure() is None


def test_checked_rows_show_their_state_and_redraw_in_place(tmp_path, tty_pair):
    """The screen is drawn once, redrawn in place and cleared after confirmation."""
    master, slave, output = tty_pair(b"\x1b[B \x1b[B\r")
    app, _, data, _ = build_app(tmp_path, FakeTTY(slave), output)

    app.check_message(record())

    screen = output.getvalue()
    assert screen.count("Anything you did with it?") == 1
    assert re.search(r"\[x\] Clicked the link", screen)
    [saved] = data.load(strict=True)
    assert saved["exposure"]["clicked"] is True
    assert saved["exposure"]["downloaded"] is False
    assert "Saved report updated." in str(app._io_manager._terminal.write.call_args_list)
