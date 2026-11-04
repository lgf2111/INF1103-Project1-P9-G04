# local_settings.py
# Tiny local settings store (JSON). Used for machine-specific preferences like
# the user's email folder, so we only ask for them once. OWNER: Lee Guan Feng.
#
# The file is gitignored, so each person's settings stay on their own machine.

import json
import os
import tempfile

import logging_setup

logger = logging_setup.get_logger(__name__)

FILE = ".phishreport_config.json"


def _unique_settings(pairs):
    """Build a settings object, raising ValueError for duplicate JSON keys."""
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Local settings contain duplicate fields.")
        data[key] = value
    return data


def load_settings(*, strict: bool = False) -> dict:
    """Read a preferences object; return {} when the file is missing.

    Log read/parse failures and return {} by default. With strict=True,
    propagate those failures so an update cannot overwrite unreadable data.
    """
    try:
        with open(FILE, encoding="utf-8") as settings_file:
            data = json.load(settings_file, object_pairs_hook=_unique_settings)
        if not isinstance(data, dict):
            raise ValueError("Local settings must be a JSON object.")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        logging_setup.log_failure(logger, "Could not read local config; using defaults.")
        if strict:
            raise
        return {}


def get_setting(key: str, default=None):
    """Return a saved preference, or default if absent or settings cannot be read."""
    return load_settings().get(key, default)


def save_setting(key: str, value) -> bool:
    """Atomically save a preference; preserve existing bytes on any failed update."""
    temporary = None
    try:
        data = load_settings(strict=True)
        data[key] = value
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(os.path.abspath(FILE)),
            suffix=".tmp",
            delete=False,
        ) as settings_file:
            temporary = settings_file.name
            json.dump(data, settings_file, indent=2, allow_nan=False)
            settings_file.flush()
            os.fsync(settings_file.fileno())
        os.replace(temporary, FILE)
        return True
    except (OSError, ValueError, RecursionError):
        logging_setup.log_failure(logger, "Could not save local config.")
        return False
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                logging_setup.log_failure(logger, "Could not remove temporary local config.")
