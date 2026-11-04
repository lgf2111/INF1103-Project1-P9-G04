"""Signed-in dashboard shell and its local navigation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.ui.branding import brand_mark


class DashboardShell:
    """Build the signed-in shell and delegate sign-out to the window."""

    def __init__(self, on_sign_out: Callable[[], None]) -> None:
        self._on_sign_out = on_sign_out
        self.widget = self._build_dashboard_shell()

    def _sign_out(self) -> None:
        self._on_sign_out()

    def _build_dashboard_shell(self) -> QWidget:
        shell = QWidget()
        shell.setObjectName("appShell")
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 12, 28, 12)
        header_layout.setSpacing(10)
        header_layout.addWidget(brand_mark())
        brand = QLabel("PhishReport")
        brand.setObjectName("appBrand")
        header_layout.addWidget(brand)
        header_layout.addStretch(1)

        self.profile_button = QPushButton("P")
        self.profile_button.setObjectName("profileButton")
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_button.setAccessibleName("Account menu")
        self.profile_menu = QMenu(self.profile_button)
        self.profile_identity_action = self.profile_menu.addAction("Your account")
        self.profile_identity_action.setEnabled(False)
        self.profile_email_action = self.profile_menu.addAction("")
        self.profile_email_action.setEnabled(False)
        self.profile_menu.addSeparator()
        self.settings_action = self.profile_menu.addAction("Settings (locked)")
        self.settings_action.triggered.connect(self._show_locked_settings)
        self.sign_out_action = self.profile_menu.addAction("Sign out")
        self.sign_out_action.triggered.connect(self._sign_out)
        self.profile_button.clicked.connect(self._show_profile_menu)
        header_layout.addWidget(self.profile_button)
        layout.addWidget(header)

        self.account_notice = QLabel()
        self.account_notice.setObjectName("notice")
        self.account_notice.setProperty("severity", "error")
        self.account_notice.setWordWrap(True)
        self.account_notice.hide()
        layout.addWidget(self.account_notice)

        self.app_pages = QStackedWidget()
        self.dashboard_page = self._build_dashboard_page()
        self.settings_page = self._build_locked_settings_page()
        self.app_pages.addWidget(self.dashboard_page)
        self.app_pages.addWidget(self.settings_page)
        layout.addWidget(self.app_pages)
        return shell

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("appCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 36)
        layout.setSpacing(0)

        title = QLabel("Overview")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        description = QLabel("Your PhishReport workspace.")
        description.setObjectName("intro")
        description.setContentsMargins(0, 6, 0, 24)
        layout.addWidget(description)

        panel = QFrame()
        panel.setObjectName("emptyPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(8)
        panel_title = QLabel("Message assessments")
        panel_title.setObjectName("panelTitle")
        panel_layout.addWidget(panel_title)
        empty_text = QLabel(
            "There are no assessments to show yet. Message analysis will appear "
            "here when the workspace is connected."
        )
        empty_text.setObjectName("intro")
        empty_text.setWordWrap(True)
        panel_layout.addWidget(empty_text)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _build_locked_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("appCanvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 36)
        layout.setSpacing(0)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        description = QLabel("Account preferences")
        description.setObjectName("intro")
        description.setContentsMargins(0, 6, 0, 24)
        layout.addWidget(description)

        panel = QFrame()
        panel.setObjectName("emptyPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 18)
        panel_layout.setSpacing(8)
        locked_title = QLabel("Settings are locked")
        locked_title.setObjectName("lockedTitle")
        panel_layout.addWidget(locked_title)
        locked_text = QLabel("Account settings are not available in this preview.")
        locked_text.setObjectName("intro")
        locked_text.setWordWrap(True)
        panel_layout.addWidget(locked_text)
        layout.addWidget(panel)

        back_button = QPushButton("Back to overview")
        back_button.setObjectName("textButton")
        back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        back_button.clicked.connect(self._show_overview)
        layout.addWidget(back_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _show_profile_menu(self) -> None:
        self.profile_menu.popup(
            self.profile_button.mapToGlobal(QPoint(0, self.profile_button.height()))
        )

    def _show_locked_settings(self) -> None:
        self.app_pages.setCurrentWidget(self.settings_page)

    def _show_overview(self) -> None:
        self.app_pages.setCurrentWidget(self.dashboard_page)
