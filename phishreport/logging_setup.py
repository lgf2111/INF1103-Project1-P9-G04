# logging_setup.py
# One place that sets up logging for the whole app. OWNER: Lee Guan Feng.
#
# Goal: a behind-the-scenes log file that helps debug failures (e.g. the
# local file or API failing) WITHOUT leaking secrets like the API
# key into the log.
#
# Two modes, controlled by the LOG_LEVEL environment variable (set it in .env):
#   - Default (safe): records short, sanitised reasons only. No tracebacks, no
#     raw exception text. This is the team's agreed privacy rule.
#   - LOG_LEVEL=DEBUG: unlocks full detail, including tracebacks, so you can see
#     exactly why something failed while actively debugging.
#
# Logs are written to the local logs/ folder, excluded from normal Git tracking.
# Debug tracebacks can contain sensitive context; logging mode controls that detail.

import logging
import os
from logging.handlers import RotatingFileHandler

# A NullHandler on the root logger means that if AppLogging.setup() was never
# called (e.g. a module used on its own, or in some tests), log records are
# swallowed instead of falling back to Python's stderr printer. This keeps the
# CLI clean and secrets off the terminal.
logging.getLogger().addHandler(logging.NullHandler())


class AppLogging:
    """Set up and use the application's diagnostic logging.

    Logging is process-wide, so the configuration and the "already set up" flag
    live on the class. Callers ask for module loggers with get_logger() and
    report failures with log_failure(); setup() is called once by the CLI.
    """

    LOG_DIR = "logs"
    LOG_FILE = os.path.join(LOG_DIR, "phishreport.log")

    # Keep up to ~1 MB per file and a few old copies, so logs can't fill the disk.
    MAX_BYTES = 1_000_000
    BACKUP_COUNT = 3

    FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

    _configured = False

    @classmethod
    def level(cls):
        """Read LOG_LEVEL from the environment; default to INFO. Returns a logging level int.

        Unknown values fall back to INFO so a typo never silences logging.
        """
        name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
        return logging.getLevelNamesMapping().get(name, logging.INFO)

    @classmethod
    def debug_enabled(cls):
        """Return whether the configured level enables debug detail (DEBUG or lower).

        Callers use this to decide whether to log tracebacks/raw causes (debug) or a
        sanitised summary (default), so secrets stay out of normal logs.
        """
        return cls.level() <= logging.DEBUG

    @classmethod
    def setup(cls):
        """Set up app-wide logging to a rotating file in the logs/ folder.

        Call once, early in main(). Returns True if the file log is active, or False
        if the logs/ folder or file could not be opened (the app still runs without a
        file log). Safe to call more than once.
        """
        if cls._configured:
            return True

        level = cls.level()
        root = logging.getLogger()
        root.setLevel(level)

        try:
            os.makedirs(cls.LOG_DIR, exist_ok=True)
            handler = RotatingFileHandler(
                cls.LOG_FILE,
                maxBytes=cls.MAX_BYTES,
                backupCount=cls.BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return False

        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(cls.FORMAT))
        root.addHandler(handler)

        logging.getLogger(__name__).info(
            "=== logging started (level=%s) ===", logging.getLevelName(level)
        )
        cls._configured = True
        return True

    @staticmethod
    def get_logger(name):
        """Return a logger for a module. Use AppLogging.get_logger(__name__) at module top.

        Attaches a NullHandler so that, even if setup() hasn't run and the root
        logger has no handlers, records are swallowed rather than printed to the
        terminal by Python's last-resort handler.
        """
        module_logger = logging.getLogger(name)
        if not any(isinstance(h, logging.NullHandler) for h in module_logger.handlers):
            module_logger.addHandler(logging.NullHandler())
        return module_logger

    @classmethod
    def log_failure(cls, logger, summary):
        """Log a failure safely by default, with full detail only in debug mode.

        Call this from inside an 'except' block. 'summary' must be a fixed,
        developer-written message with no secrets or user content.

        - Default (LOG_LEVEL not DEBUG): logs just the summary at WARNING. No
          traceback and no raw exception text, so API keys and
          message content never reach the log.
        - LOG_LEVEL=DEBUG: logs the summary at ERROR with the full traceback
          (exc_info), so you can see exactly why it failed while debugging.
        """
        if cls.debug_enabled():
            logger.error(summary, exc_info=True)
        else:
            logger.warning(summary)
