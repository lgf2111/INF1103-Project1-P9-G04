"""Public data-layer contracts and default JSON implementation."""

from .json_storage import JsonReportStorage
from .manager import DataManager
from .storage import ReportStorage
from .validator import ReportValidator

__all__ = ["DataManager", "ReportValidator", "ReportStorage", "JsonReportStorage"]
