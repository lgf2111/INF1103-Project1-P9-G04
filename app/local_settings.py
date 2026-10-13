# local_settings.py
# Tiny local settings store (JSON). Used for machine-specific preferences like
# the user's email folder, so we only ask for them once. OWNER: Lee Guan Feng.
#
# The file is gitignored, so each person's settings stay on their own machine.

import json

import logging_setup

logger = logging_setup.get_logger(__name__)

FILE = ".phishreport_config.json"


def load_settings() -> dict:
    """Return the saved settings as a dict, or {} if none/unreadable."""
    try:
        with open(FILE, encoding="utf-8") as settings_file:
            data = json.load(settings_file)
        if not isinstance(data, dict):
            raise ValueError("Local settings must be a JSON object.")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Could not read local config; using defaults.")
        return {}


def get_setting(key: str, default=None):
    """Return a single saved setting."""
    return load_settings().get(key, default)


def save_setting(key: str, value) -> None:
    """Save a single setting, keeping the other saved values intact."""
    data = load_settings()
    data[key] = value
    try:
        with open(FILE, "w", encoding="utf-8") as settings_file:
            json.dump(data, settings_file, indent=2)
    except OSError:
        logging_setup.log_failure(logger, "Could not save local config.")
