# ai_manager/errors.py
# Shared failure logging for the AI layer. OWNER: Pair A.

from misc import logging_setup

# The application configures the destination; importing AI must not print or open files.
logger = logging_setup.get_logger("ai_manager")


def failure(stage, message, error_type):
    """Log a developer-controlled reason and construct the existing public error.

    Call only with fixed messages or known schema fields/status codes. Never pass
    record content, raw provider output or exception text. By default logs the
    reason only (no traceback); with LOG_LEVEL=DEBUG it also captures the full
    traceback to help diagnose failures. The caller decides how to continue.
    """
    logging_setup.log_failure(logger, f"stage={stage} reason={message}")
    return error_type(message)
