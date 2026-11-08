"""Focused input and output components for the CLI."""

from .eml import EmlReader
from .folder import EmlFolderPicker
from .manager import IOManager
from .presenter import ReportPresenter
from .terminal import Terminal

__all__ = ["EmlFolderPicker", "EmlReader", "IOManager", "ReportPresenter", "Terminal"]
