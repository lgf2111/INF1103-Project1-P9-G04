# misc/config.py
# Tiny local settings store (JSON). Used for machine-specific preferences like
# the user's email folder, so we only ask for them once. OWNER: Lee Guan Feng.
#
# The file is gitignored, so each person's settings stay on their own machine.

import json
import os

from misc import logging_setup

logger = logging_setup.get_logger(__name__)

FILE = ".phishreport_config.json"


def load():
    """Return the saved settings as a dict, or {} if none/unreadable."""
    if not os.path.exists(FILE):
        return {}
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logging_setup.log_failure(logger, "Could not read local config; using defaults.")
        return {}


def get(key, default=None):
    """Return a single saved setting."""
    return load().get(key, default)


def set(key, value):
    """Save a single setting, keeping the other saved values intact."""
    data = load()
    data[key] = value
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        logging_setup.log_failure(logger, "Could not save local config.")
