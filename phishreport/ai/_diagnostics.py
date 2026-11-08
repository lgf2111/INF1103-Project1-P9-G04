"""Shared failure diagnostics for AI operations."""

import logging

from phishreport import logging_setup


class FailureDiagnostics:
    """Log developer-controlled failure reasons and build the public errors."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logging_setup.get_logger("ai_manager") if logger is None else logger

    @property
    def logger(self) -> logging.Logger:
        """Return the logger shared by AI components for operational messages."""
        return self._logger

    def failure(self, stage, message, error_type):
        """Log a developer-controlled reason and construct the existing public error.

        Call only with fixed messages or known schema fields/status codes. Never pass
        record content, raw provider output or exception text. By default logs the
        reason only (no traceback); with LOG_LEVEL=DEBUG it also captures the full
        traceback to help diagnose failures. The caller decides how to continue.
        """
        logging_setup.log_failure(self._logger, f"stage={stage} reason={message}")
        return error_type(message)
