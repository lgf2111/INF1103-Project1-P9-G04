"""Branding widgets shared by the desktop views."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


def brand_mark() -> QLabel:
    mark = QLabel("P")
    mark.setObjectName("brandMark")
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setFixedSize(38, 38)
    mark.setStyleSheet(
        "border: 1px solid #0a0a0a; border-radius: 8px; font-size: 20px; font-weight: 600;"
    )
    mark.setAccessibleName("PhishReport mark")
    return mark
