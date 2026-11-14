"""Provider diagnostics preserve structured failures and logging policy."""

import logging

import pytest

from phishreport.ai._diagnostics import FailureDiagnostics
from phishreport.ai._provider_errors import ProviderFailure, ProviderFailureReason


def test_provider_failure_logs_safe_summary_with_active_private_cause(caplog, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    logger = logging.getLogger("tests.ai_diagnostics.safe")
    diagnostics = FailureDiagnostics(logger)

    with caplog.at_level(logging.WARNING, logger=logger.name):
        try:
            raise ValueError("private-token-123 raw provider body")
        except ValueError:
            error = diagnostics.provider_failure(ProviderFailureReason.TRANSPORT)

    assert isinstance(error, ProviderFailure)
    assert error.reason is ProviderFailureReason.TRANSPORT
    assert error.status_code is None
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.name == logger.name
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "stage=call_api reason=Could not complete the AI request."
    assert record.exc_info is None
    assert "private-token-123" not in caplog.text
    assert "raw provider body" not in caplog.text


def test_provider_failure_preserves_http_metadata(caplog, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    logger = logging.getLogger("tests.ai_diagnostics.http")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        error = FailureDiagnostics(logger).provider_failure(
            ProviderFailureReason.HTTP, status_code=429
        )

    assert isinstance(error, ProviderFailure)
    assert error.reason is ProviderFailureReason.HTTP
    assert error.status_code == 429
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage() == (
        "stage=call_api reason=AI provider returned HTTP 429."
    )


@pytest.mark.parametrize(
    ("reason", "status_code", "error_type"),
    [
        ("private-token-123", None, TypeError),
        (ProviderFailureReason.HTTP, True, TypeError),
        (ProviderFailureReason.HTTP, 600, ValueError),
        (ProviderFailureReason.HTTP, None, ValueError),
        (ProviderFailureReason.TIMEOUT, 429, ValueError),
    ],
)
def test_invalid_provider_failure_emits_no_diagnostic(
    caplog, reason, status_code, error_type
):
    logger = logging.getLogger("tests.ai_diagnostics.invalid")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        with pytest.raises(error_type):
            FailureDiagnostics(logger).provider_failure(reason, status_code=status_code)

    assert not caplog.records


def test_provider_failure_keeps_debug_traceback_policy(caplog, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logger = logging.getLogger("tests.ai_diagnostics.debug")
    cause = ValueError("debug-only provider context")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        try:
            raise cause
        except ValueError:
            error = FailureDiagnostics(logger).provider_failure(
                ProviderFailureReason.TIMEOUT
            )

    assert error.reason is ProviderFailureReason.TIMEOUT
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == "stage=call_api reason=The AI request timed out."
    assert record.exc_info[1] is cause
