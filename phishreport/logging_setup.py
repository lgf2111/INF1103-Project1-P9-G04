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
# Each local calendar day gets its own file, so old days can be removed without
# rewriting one long file. Debug tracebacks can contain sensitive context;
# logging mode controls that detail.

import logging
import os
import re
import time
from logging.handlers import TimedRotatingFileHandler

# A NullHandler on the root logger means that if AppLogging.setup() was never
# called (e.g. a module used on its own, or in some tests), log records are
# swallowed instead of falling back to Python's stderr printer. This keeps the
# CLI clean and secrets off the terminal.
logging.getLogger().addHandler(logging.NullHandler())

# HTTP client libraries log full request URLs at INFO. Telegram puts its bot
# token in the URL path, so these loggers stay quiet for every entry point.
HTTP_CLIENT_LOGGERS = ("httpx", "httpcore", "urllib3")


class SecretRedactor:
    """Mask credentials in a rendered log message."""

    _PATTERNS = (
        (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot<redacted>"),
        (re.compile(r"(?<!\w)\d{8,10}:[A-Za-z0-9_-]{20,}"), "<redacted>"),
        (
            re.compile(r"(?i)\b(token|api_key|apikey|secret|password|key)=([^&\s\"'<>;]+)"),
            r"\1=<redacted>",
        ),
        (re.compile(r"(?i)\bBearer\s+[^\s\"',;]+"), "Bearer <redacted>"),
        (re.compile(r"gsk_[A-Za-z0-9_-]+"), "<redacted>"),
    )

    def redact_secrets(self, message: str) -> str:
        """Mask credentials while preserving the rest of a rendered log message."""
        for pattern, replacement in self._PATTERNS:
            message = pattern.sub(replacement, message)
        return message


class SecretRedactingFilter(logging.Filter):
    """Redact a record's fully rendered message, including %-style arguments."""

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or SecretRedactor()

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the message in place and always keep the record."""
        rendered = record.getMessage()
        redacted = self._redactor.redact_secrets(rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


class DailyLogFileHandler(TimedRotatingFileHandler):
    """Write one file per local day, named logs/<prefix>-YYYY-MM-DD.log.

    TimedRotatingFileHandler normally renames the live file to an archive name.
    Here the live file already carries its date, so a rollover switches to the
    next day's file and leaves the finished day in place. The namer still maps
    a dated suffix to the dated file name so the inherited retention can find
    old days and remove them.
    """

    def __init__(
        self,
        log_dir: str,
        *,
        prefix: str = "phishreport",
        backup_count: int = 14,
    ) -> None:
        self._log_dir = os.path.abspath(log_dir)
        self._prefix = prefix
        super().__init__(
            self._path_for(time.time()),
            when="midnight",
            backupCount=backup_count,
            encoding="utf-8",
            utc=False,
        )
        self.namer = self._dated_name

    def _path_for(self, moment: float) -> str:
        """Return the dated file path for a timestamp in local time."""
        day = time.strftime("%Y-%m-%d", time.localtime(moment))
        return os.path.join(self._log_dir, f"{self._prefix}-{day}.log")

    def _dated_name(self, default_name: str) -> str:
        """Map a rotation name such as <file>.<date> to the dated file name."""
        suffix = default_name.rsplit(".", 1)[-1]
        return os.path.join(self._log_dir, f"{self._prefix}-{suffix}.log")

    def doRollover(self) -> None:
        """Open the new day's file, then remove days beyond the backup count."""
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = self._path_for(time.time())
        if not self.delay:
            self.stream = self._open()
        if self.backupCount > 0:
            for path in self.getFilesToDelete():
                os.remove(path)
        self.rolloverAt = self.computeRollover(int(time.time()))


class AppLogging:
    """Set up and use the application's diagnostic logging.

    Logging is process-wide, so the configuration and the "already set up" flag
    live on the class. Callers ask for module loggers with get_logger() and
    report failures with log_failure(); setup() is called once by the CLI.
    """

    LOG_DIR = "logs"
    LOG_PREFIX = "phishreport"
    # Local naming pattern for the live file: logs/phishreport-YYYY-MM-DD.log.
    LOG_FILE = os.path.join(LOG_DIR, f"{LOG_PREFIX}-%Y-%m-%d.log")

    # Keep two weeks of daily files, so logs can't fill the disk.
    BACKUP_COUNT = 14

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
        """Set up app-wide logging to one dated file per local day in logs/.

        Call once, early in main(). Returns True if the file log is active, or False
        if the logs/ folder or file could not be opened (the app still runs without a
        file log). Safe to call more than once.
        """
        # Every entry point (CLI, bot, future adapters) shares this setup. HTTP
        # client libraries log full request URLs at INFO, and Telegram embeds the
        # bot token in the URL path, so keep those loggers at WARNING or above.
        for name in HTTP_CLIENT_LOGGERS:
            client_logger = logging.getLogger(name)
            if client_logger.level < logging.WARNING:
                client_logger.setLevel(logging.WARNING)

        if cls._configured:
            return True

        level = cls.level()
        root = logging.getLogger()
        root.setLevel(level)

        try:
            os.makedirs(cls.LOG_DIR, exist_ok=True)
            handler = DailyLogFileHandler(
                cls.LOG_DIR,
                prefix=cls.LOG_PREFIX,
                backup_count=cls.BACKUP_COUNT,
            )
        except OSError:
            return False

        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(cls.FORMAT))
        # Defence in depth: redact secrets from every record this app writes,
        # in case a library or future adapter logs a credential at INFO+.
        handler.addFilter(SecretRedactingFilter(SecretRedactor()))
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
