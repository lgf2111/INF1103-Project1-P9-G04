"""Startup ordering for the combined CLI and Telegram mode."""

import asyncio
import sys
import threading
import time

from phishreport.bot.main import startup_guide
from phishreport.both import (
    ALL_STOP_LINE,
    BOT_STOP_LINE,
    BothApp,
    all_startup_guide,
    build_bot_application,
)
from phishreport.data import DataManager, JsonReportStorage

GUIDE_LINES = (
    "PhishReport bot is running.",
    "  1. Open Telegram and message @probe_bot.",
    "  5. After linking, new emails are checked every minute.",
    ALL_STOP_LINE,
)


def write(line):
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def test_all_mode_prints_the_bot_guide_before_the_cli_banner(capsys):
    ready = threading.Event()

    def bot_worker(stop_event):
        # A real initialiser takes a moment before it can write the guide.
        time.sleep(0.05)
        for line in GUIDE_LINES:
            write(line)
        ready.set()
        stop_event.wait(10)

    def cli_loop():
        write("\n=== PhishReport ===")
        write("1. Check a message")
        write("5. Quit")
        sys.stdout.write("Choose 1-5: ")
        sys.stdout.flush()

    assert BothApp(bot_worker, cli_loop, ready=ready, ready_timeout=5).run() == 0

    out = capsys.readouterr().out
    banner = out.index("=== PhishReport ===")
    assert out.count("=== PhishReport ===") == 1
    assert out.index("Starting the CLI and the Telegram bot in one process.") < banner
    for line in GUIDE_LINES:
        assert out.index(line) < banner
    # The prompt is the final line, without a trailing newline.
    assert out.endswith("Choose 1-5: ")
    assert out.splitlines()[-1] == "Choose 1-5: "


def test_timeout_prints_one_warning_and_still_starts_the_cli(capsys):
    ready = threading.Event()
    cli_started = []

    def silent_bot(stop_event):
        stop_event.wait(10)

    def cli_loop():
        cli_started.append(True)

    assert BothApp(silent_bot, cli_loop, ready=ready, ready_timeout=0.05).run() == 0

    captured = capsys.readouterr()
    warnings = [line for line in captured.err.splitlines() if line.startswith("Warning:")]
    assert warnings == [
        "Warning: the bot did not finish starting; continuing with the CLI."
    ]
    assert cli_started == [True]


def test_all_startup_guide_uses_the_combined_stop_line():
    guide = all_startup_guide("probe_bot")

    assert ALL_STOP_LINE in guide
    assert BOT_STOP_LINE not in guide
    assert guide.rstrip().endswith(ALL_STOP_LINE)


def test_bot_only_startup_guide_is_unchanged():
    assert startup_guide("probe_bot").rstrip().endswith(BOT_STOP_LINE)


def test_post_init_reports_readiness_after_writing_the_guide(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PHISHREPORT_FEEDBACK_PATH", str(tmp_path / "feedback.json"))
    monkeypatch.setenv("PHISHREPORT_GMAIL_PATH", str(tmp_path / "gmail.json"))
    ready = threading.Event()
    data_manager = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    application = build_bot_application(
        data_manager,
        "123456:AAExampleTokenNotReal_0123456789abcdefg",
        ready=ready,
        guide=lambda username: f"GUIDE for {username}",
    )

    async def no_commands(*args, **kwargs):
        return None

    async def no_run(self):
        return None

    def fake_monitor(*args, **kwargs):
        return type("FakeMonitor", (), {"run": no_run})()

    monkeypatch.setattr(type(application.bot), "username", property(lambda self: "probe_bot"))
    monkeypatch.setattr(type(application.bot), "set_my_commands", no_commands)
    monkeypatch.setattr("phishreport.both.EmailMonitor", fake_monitor)

    asyncio.run(application.post_init(application))

    assert ready.is_set()
    assert "GUIDE for probe_bot" in capsys.readouterr().out
