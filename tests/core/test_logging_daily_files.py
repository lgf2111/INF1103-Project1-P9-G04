"""Daily log files: midnight rotation, retention, redaction and setup."""

import logging
import time
from logging.handlers import TimedRotatingFileHandler

import pytest

from phishreport.logging_setup import AppLogging

TELEGRAM_TOKEN = "123456789:AAFakeSyntheticTokenForTests"
HTTP_CLIENT_LOGGERS = ("httpx", "httpcore", "urllib3")


class FakeClock:
    """Stand-in for time.time() so a test can cross local midnight."""

    def __init__(self, moment):
        self.moment = moment

    def time(self):
        return self.moment


def local_timestamp(year, month, day, hour=12, minute=0, second=0):
    """Return the local timestamp for a calendar moment."""
    return time.mktime((year, month, day, hour, minute, second, 0, 0, -1))


@pytest.fixture
def daily_logs(tmp_path, monkeypatch):
    """Point AppLogging at a temporary logs folder and clean up its handler."""
    monkeypatch.setattr(AppLogging, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(AppLogging, "_configured", False)
    for name in HTTP_CLIENT_LOGGERS:
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "level", logger.level)
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield tmp_path / "logs"

    for handler in root.handlers[:]:
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(original_level)
    AppLogging._configured = False


def added_handler(before):
    """Return the one app handler this test installed."""
    added = [handler for handler in logging.getLogger().handlers
             if handler not in before]
    assert len(added) == 1
    return added[0]


def test_records_roll_into_the_next_dated_file_at_midnight(daily_logs, monkeypatch):
    clock = FakeClock(local_timestamp(2026, 11, 17, 23, 59, 30))
    monkeypatch.setattr(time, "time", clock.time)
    assert AppLogging.setup() is True

    logger = logging.getLogger("phishreport.daily")
    logger.warning("before midnight")
    first = daily_logs / "phishreport-2026-11-17.log"
    assert "before midnight" in first.read_text(encoding="utf-8")

    clock.moment = local_timestamp(2026, 11, 18, 0, 0, 30)
    logger.warning("after midnight")

    second = daily_logs / "phishreport-2026-11-18.log"
    assert second.is_file()
    assert "after midnight" in second.read_text(encoding="utf-8")
    assert "after midnight" not in first.read_text(encoding="utf-8")
    assert "before midnight" in first.read_text(encoding="utf-8")


def test_rotation_keeps_only_the_newest_fourteen_dated_files(daily_logs, monkeypatch):
    clock = FakeClock(local_timestamp(2026, 11, 20))
    monkeypatch.setattr(time, "time", clock.time)
    daily_logs.mkdir(parents=True)
    for day in range(1, 21):
        (daily_logs / f"phishreport-2026-11-{day:02d}.log").touch()
    before = logging.getLogger().handlers[:]
    assert AppLogging.setup() is True

    added_handler(before).doRollover()

    remaining = sorted(path.name for path in daily_logs.glob("phishreport-*.log"))
    assert remaining == [
        f"phishreport-2026-11-{day:02d}.log" for day in range(7, 21)
    ]


def test_dated_file_still_redacts_a_synthetic_bot_token(daily_logs, monkeypatch):
    clock = FakeClock(local_timestamp(2026, 11, 17, 10, 0, 0))
    monkeypatch.setattr(time, "time", clock.time)
    assert AppLogging.setup() is True

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.INFO)
    httpx_logger.info(
        'HTTP Request: POST https://api.telegram.org/bot%s/getMe "HTTP/1.1 200 OK"',
        TELEGRAM_TOKEN,
    )

    text = (daily_logs / "phishreport-2026-11-17.log").read_text(encoding="utf-8")
    assert TELEGRAM_TOKEN not in text
    assert "https://api.telegram.org/bot<redacted>/getMe" in text


def test_setup_creates_a_missing_log_directory_and_writes(daily_logs, monkeypatch, tmp_path):
    clock = FakeClock(local_timestamp(2026, 11, 17))
    monkeypatch.setattr(time, "time", clock.time)
    missing = tmp_path / "missing" / "logs"
    monkeypatch.setattr(AppLogging, "LOG_DIR", str(missing))

    assert AppLogging.setup() is True
    logging.getLogger("phishreport.daily").warning("folder created")

    path = missing / "phishreport-2026-11-17.log"
    assert path.is_file()
    assert "folder created" in path.read_text(encoding="utf-8")


def test_handler_uses_midnight_rotation_and_two_week_retention(daily_logs, monkeypatch):
    clock = FakeClock(local_timestamp(2026, 11, 17))
    monkeypatch.setattr(time, "time", clock.time)
    before = logging.getLogger().handlers[:]
    assert AppLogging.setup() is True

    handler = added_handler(before)
    assert isinstance(handler, TimedRotatingFileHandler)
    assert handler.when == "MIDNIGHT"
    assert handler.backupCount == 14
    assert handler.encoding == "utf-8"
    assert handler.utc is False
    assert callable(handler.namer)
