"""Background workers for blocking authentication operations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

from app_gui.auth_api import AuthApiError

LOGGER = logging.getLogger(__name__)


class ApiWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation

    def run(self) -> None:
        try:
            self.succeeded.emit(self.operation())
        except AuthApiError as error:
            self.failed.emit(error)
        except Exception:
            LOGGER.exception("Unexpected authentication request failure")
            self.failed.emit(
                AuthApiError("The authentication request failed unexpectedly. Please try again.")
            )
