# logging_setup.py
# One place that sets up logging for the whole app. OWNER: Lee Guan Feng.
#
# Goal: a behind-the-scenes log file that helps debug failures (e.g. the
# database not connecting) WITHOUT leaking secrets like the database URL or API
# key into the log.
#
# Two modes, controlled by the LOG_LEVEL environment variable (set it in .env):
#   - Default (safe): records short, sanitised reasons only. No tracebacks, no
#     raw exception text. This is the team's agreed privacy rule.
#   - LOG_LEVEL=DEBUG: unlocks full detail, including tracebacks, so you can see
#     exactly why something failed while actively debugging.
#
# Either way the log goes to the gitignored logs/ folder, so it never leaves
# your machine.

import logging
import os
from logging.handlers import RotatingFileHandler

# A NullHandler on the root logger means that if setup_logging() was never
# called (e.g. a module used on its own, or in some tests), log records are
# swallowed instead of falling back to Python's stderr printer. This keeps the
# CLI clean and secrets off the terminal.
logging.getLogger().addHandler(logging.NullHandler())

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "phishreport.log")

# Keep up to ~1 MB per file and a few old copies, so logs can't fill the disk.
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def _resolve_level():
    """Read LOG_LEVEL from the environment; default to INFO. Returns a logging level int.

    Unknown values fall back to INFO so a typo never silences logging.
    """
    name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, name, logging.INFO)


def debug_enabled():
    """True when the user asked for full detail (LOG_LEVEL=DEBUG).

    Callers use this to decide whether to log tracebacks/raw causes (debug) or a
    sanitised summary (default), so secrets stay out of normal logs.
    """
    return _resolve_level() <= logging.DEBUG


def setup_logging():
    """Set up app-wide logging to a rotating file in the logs/ folder.

    Call once, early in main(). Returns True if the file log is active, or False
    if the logs/ folder or file could not be opened (the app still runs without a
    file log). Safe to call more than once.
    """
    global _configured
    if _configured:
        return True

    level = _resolve_level()
    root = logging.getLogger()
    root.setLevel(level)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        return False

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)

    logging.getLogger(__name__).info("=== logging started (level=%s) ===",
                                     logging.getLevelName(level))
    _configured = True
    return True


def get_logger(name):
    """Return a logger for a module. Use get_logger(__name__) at module top.

    Attaches a NullHandler so that, even if setup_logging() hasn't run and the
    root logger has no handlers, records are swallowed rather than printed to the
    terminal by Python's last-resort handler.
    """
    module_logger = logging.getLogger(name)
    if not any(isinstance(h, logging.NullHandler) for h in module_logger.handlers):
        module_logger.addHandler(logging.NullHandler())
    return module_logger


def log_failure(logger, summary):
    """Log a failure safely by default, with full detail only in debug mode.

    Call this from inside an 'except' block. 'summary' must be a fixed,
    developer-written message with no secrets or user content.

    - Default (LOG_LEVEL not DEBUG): logs just the summary at WARNING. No
      traceback and no raw exception text, so the database URL, API key and
      message content never reach the log.
    - LOG_LEVEL=DEBUG: logs the summary at ERROR with the full traceback
      (exc_info), so you can see exactly why it failed while debugging.
    """
    if debug_enabled():
        logger.error(summary, exc_info=True)
    else:
        logger.warning(summary)
