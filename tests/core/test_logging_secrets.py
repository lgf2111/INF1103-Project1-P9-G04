"""Secrets must not reach the application log file."""

import logging
from pathlib import Path

import pytest

from phishreport.logging_setup import AppLogging

TELEGRAM_TOKEN = "123456789:AAFakeSyntheticTokenForTests"


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Configure the real file handler against a temporary logs folder."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setattr(AppLogging, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(AppLogging, "LOG_FILE", str(tmp_path / "logs" / "phishreport.log"))
    monkeypatch.setattr(AppLogging, "_configured", False)
    for name in ("httpx", "httpcore", "urllib3"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "level", logger.level)
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    assert AppLogging.setup() is True

    yield Path(AppLogging.LOG_FILE)

    for handler in root.handlers[:]:
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(original_level)
    AppLogging._configured = False


def test_httpx_record_keeps_the_line_with_a_redacted_telegram_token(log_file):
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.INFO)

    httpx_logger.info(
        'HTTP Request: POST https://api.telegram.org/bot%s/getMe "HTTP/1.1 200 OK"',
        TELEGRAM_TOKEN,
    )

    text = log_file.read_text(encoding="utf-8")
    assert TELEGRAM_TOKEN not in text
    assert "HTTP Request: POST" in text
    assert "https://api.telegram.org/bot<redacted>/getMe" in text


@pytest.mark.parametrize(
    ("message", "secret", "expected"),
    [
        (
            "callback failed: https://example.test/hook?token=synthetic-query-value",
            "synthetic-query-value",
            "https://example.test/hook?token=<redacted>",
        ),
        (
            "Authorization: Bearer synthetic-bearer-value",
            "synthetic-bearer-value",
            "Authorization: Bearer <redacted>",
        ),
        (
            "provider rejected gsk_syntheticGroqValue123",
            "gsk_syntheticGroqValue123",
            "provider rejected <redacted>",
        ),
        (
            "form body api_key=synthetic-api-key&password=synthetic-password",
            "synthetic-api-key",
            "api_key=<redacted>",
        ),
    ],
)
def test_rendered_records_mask_query_bearer_and_groq_secrets(
    log_file, message, secret, expected
):
    logging.getLogger("phishreport.test").info(message)

    text = log_file.read_text(encoding="utf-8")
    assert secret not in text
    assert expected in text


def test_ordinary_info_message_is_written_unchanged(log_file):
    message = "Saved report 7 with no credentials in it."

    logging.getLogger("phishreport.test").info(message)

    assert message in log_file.read_text(encoding="utf-8")


def test_http_client_loggers_stay_above_info(log_file):
    for name in ("httpx", "httpcore", "urllib3"):
        logger = logging.getLogger(name)
        assert logger.level >= logging.WARNING
        logger.info("synthetic request line for %s", name)

    text = log_file.read_text(encoding="utf-8")
    assert "synthetic request line" not in text
