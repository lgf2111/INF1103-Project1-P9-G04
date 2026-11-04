"""Authentication-window layout and page stack."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gui.ui.auth_pages import (
    AuthPage,
    ForgotPasswordPage,
    LoginPage,
    ResetPasswordPage,
    SignupPage,
)
from gui.ui.branding import brand_mark


class AuthShell:
    """Create the split-branding layout and authentication page stack."""

    def __init__(self, reset_token: str = "") -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.brand_panel = QWidget()
        self.brand_panel.setObjectName("brandPanel")
        brand_layout = QVBoxLayout(self.brand_panel)
        brand_layout.setContentsMargins(52, 48, 52, 44)
        brand_layout.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.addWidget(brand_mark())
        brand_name = QLabel("PhishReport")
        brand_name.setObjectName("brandName")
        brand_row.addSpacing(10)
        brand_row.addWidget(brand_name)
        brand_row.addStretch(1)
        brand_layout.addLayout(brand_row)
        brand_layout.addStretch(1)

        brand_title = QLabel("Pause before you trust a message.")
        brand_title.setObjectName("brandTitle")
        brand_title.setWordWrap(True)
        brand_layout.addWidget(brand_title)
        brand_copy = QLabel(
            "Assess suspicious emails, texts and chats, then decide what to do next."
        )
        brand_copy.setObjectName("intro")
        brand_copy.setWordWrap(True)
        brand_copy.setContentsMargins(0, 18, 0, 0)
        brand_layout.addWidget(brand_copy)
        brand_layout.addStretch(1)

        divider = QFrame()
        divider.setObjectName("rule")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        brand_layout.addWidget(divider)
        channels = QLabel("Email       Text messages       Chat")
        channels.setContentsMargins(0, 18, 0, 0)
        brand_layout.addWidget(channels)
        footer = QLabel("A careful next step starts here.")
        footer.setObjectName("muted")
        footer.setContentsMargins(0, 28, 0, 0)
        brand_layout.addWidget(footer)

        pages = QStackedWidget()
        pages.setContentsMargins(0, 0, 0, 0)
        page_layout = QVBoxLayout()
        page_host = QWidget()
        page_host.setLayout(page_layout)
        page_layout.setContentsMargins(76, 48, 76, 44)
        page_layout.addStretch(1)
        self.stack = QStackedWidget()
        page_layout.addWidget(self.stack)
        page_layout.addStretch(1)
        pages.addWidget(page_host)

        self.auth_pages: dict[str, AuthPage] = {
            "login": LoginPage(),
            "signup": SignupPage(),
            "forgot": ForgotPasswordPage(),
        }
        for key, page in self.auth_pages.items():
            self.stack.addWidget(page)
            page.setProperty("route", key)

        self.reset_page = ResetPasswordPage(reset_token) if reset_token else None
        if self.reset_page:
            self.stack.addWidget(self.reset_page)

        root_layout.addWidget(self.brand_panel, 9)
        root_layout.addWidget(pages, 11)
        self.widget = root
