"""Launch the standalone PhishReport desktop authentication GUI."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_gui.auth_api import AuthApiClient, AuthApiError

LOGGER = logging.getLogger(__name__)
PASSWORD_MIN_LENGTH = 12

STYLESHEET = """
QWidget {
    color: #0a0a0a;
    font-size: 14px;
}
QMainWindow, QStackedWidget { background: #ffffff; }
QWidget#brandPanel { background: #f2f4f7; }
QLabel#brandName { font-size: 18px; font-weight: 600; }
QLabel#brandTitle { font-size: 32px; font-weight: 500; }
QLabel#pageTitle { font-size: 26px; font-weight: 600; }
QLabel#intro, QLabel#muted { color: #555b63; }
QLabel#notice { padding: 11px 13px; border-radius: 6px; }
QLabel#notice[severity="error"] { color: #831c1e; background: #ffedea; }
QLabel#notice[severity="success"] { color: #124a2a; background: #e5f5e9; }
QLabel#notice[severity="info"] { color: #30343a; background: #f2f4f7; }
QLabel#fieldError { color: #831c1e; font-size: 13px; }
QLineEdit {
    min-height: 42px;
    padding: 0 11px;
    border: 1px solid #b7bdc5;
    border-radius: 6px;
    background: #ffffff;
    selection-background-color: #1d5fbf;
}
QLineEdit:focus { border: 2px solid #1d5fbf; }
QLineEdit[invalid="true"] { border: 1px solid #831c1e; }
QLineEdit#passwordField { border-top-right-radius: 0; border-bottom-right-radius: 0; }
QPushButton#passwordToggle {
    min-width: 62px;
    padding: 0 10px;
    border-left: 0;
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    color: #555b63;
}
QPushButton {
    min-height: 42px;
    padding: 0 15px;
    border: 1px solid #b7bdc5;
    border-radius: 6px;
    background: #ffffff;
}
QPushButton:hover { background: #f2f4f7; }
QPushButton:focus { border: 2px solid #1d5fbf; }
QPushButton:disabled { color: #555b63; background: #eeeeee; }
QPushButton#primary {
    border-color: #141414;
    background: #141414;
    color: #ffffff;
    font-weight: 500;
}
QPushButton#primary:hover { background: #303030; }
QPushButton#textButton {
    min-height: 32px;
    padding: 0;
    border: 0;
    background: transparent;
    color: #0a0a0a;
    text-decoration: underline;
}
QPushButton#textButton:hover { color: #1d5fbf; }
QFrame#rule { color: #d7dbe0; }
"""


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


def brand_mark() -> QLabel:
    mark = QLabel("P")
    mark.setObjectName("brandMark")
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setFixedSize(38, 38)
    mark.setStyleSheet(
        "border: 1px solid #0a0a0a; border-radius: 8px; "
        "font-size: 20px; font-weight: 600;"
    )
    mark.setAccessibleName("PhishReport mark")
    return mark


class AuthPage(QWidget):
    navigate = Signal(str)
    submit = Signal(str, dict)

    def __init__(self, title: str, intro: str) -> None:
        super().__init__()
        self.title = title
        self.intro = intro
        self.fields: dict[str, QLineEdit] = {}
        self.field_errors: dict[str, QLabel] = {}
        self.submit_button: QPushButton | None = None
        self.notice: QLabel | None = None

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addStretch(1)

        self.heading = QLabel(title)
        self.heading.setObjectName("pageTitle")
        self.heading.setWordWrap(True)
        self.layout.addWidget(self.heading)

        self.description = QLabel(intro)
        self.description.setObjectName("intro")
        self.description.setWordWrap(True)
        self.description.setContentsMargins(0, 8, 0, 24)
        self.layout.addWidget(self.description)

        self.form = QVBoxLayout()
        self.form.setSpacing(14)
        self.layout.addLayout(self.form)

        self.footer = QHBoxLayout()
        self.footer.setSpacing(4)
        self.layout.addLayout(self.footer)
        self.layout.addStretch(1)

    def add_field(
        self,
        key: str,
        label: str,
        placeholder: str = "",
        password: bool = False,
        hint: str | None = None,
    ) -> QLineEdit:
        field_label = QLabel(label)
        self.form.addWidget(field_label)

        field = QLineEdit()
        field.setObjectName(key)
        field.setAccessibleName(label)
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(not password)
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setObjectName("passwordField")
            toggle = QPushButton("Show")
            toggle.setObjectName("passwordToggle")
            toggle.setCheckable(True)
            toggle.setAccessibleName("Show password")
            toggle.toggled.connect(
                partial(self._set_password_visibility, field, toggle)
            )
            row = QHBoxLayout()
            row.setSpacing(0)
            row.addWidget(field, 1)
            row.addWidget(toggle)
            self.form.addLayout(row)
        else:
            self.form.addWidget(field)
        self.fields[key] = field

        if hint:
            help_label = QLabel(hint)
            help_label.setObjectName("muted")
            help_label.setWordWrap(True)
            self.form.addWidget(help_label)

        error_label = QLabel()
        error_label.setObjectName("fieldError")
        error_label.setWordWrap(True)
        error_label.hide()
        self.form.addWidget(error_label)
        self.field_errors[key] = error_label
        return field

    def add_notice(self) -> None:
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        self.notice.setProperty("severity", "info")
        self.notice.hide()
        self.form.insertWidget(0, self.notice)

    def add_submit(self, label: str, action: str) -> None:
        self.submit_button = QPushButton(label)
        self.submit_button.setObjectName("primary")
        self.submit_button.setDefault(True)
        self.submit_button.clicked.connect(lambda: self.submit.emit(action, self.values()))
        self.form.addSpacing(3)
        self.form.addWidget(self.submit_button)

    def add_link(self, prefix: str, label: str, destination: str) -> None:
        self.footer.addStretch(1)
        if prefix:
            text = QLabel(prefix)
            text.setObjectName("muted")
            self.footer.addWidget(text)
        button = QPushButton(label)
        button.setObjectName("textButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.navigate.emit(destination))
        self.footer.addWidget(button)
        self.footer.addStretch(1)

    def add_spacer_link(self, label: str, destination: str) -> None:
        button = QPushButton(label)
        button.setObjectName("textButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.navigate.emit(destination))
        self.form.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)

    def values(self) -> dict[str, str]:
        return {
            key: field.text()
            if key.lower().endswith("password")
            else field.text().strip()
            for key, field in self.fields.items()
        }

    def set_busy(self, busy: bool, label: str | None = None) -> None:
        for field in self.fields.values():
            field.setEnabled(not busy)
        if self.submit_button:
            self.submit_button.setEnabled(not busy)
            if busy and label:
                self.submit_button.setText(label)
            elif not busy:
                self.submit_button.setText(self.submit_button.property("normalText"))

    def set_notice(self, message: str, severity: str = "error") -> None:
        if self.notice is None:
            self.add_notice()
        assert self.notice is not None
        self.notice.setText(message)
        self.notice.setProperty("severity", severity)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.show()

    def clear_notice(self) -> None:
        if self.notice:
            self.notice.hide()
        for label in self.field_errors.values():
            label.clear()
            label.hide()
        for field in self.fields.values():
            field.setProperty("invalid", False)
            field.style().unpolish(field)
            field.style().polish(field)

    def show_field_errors(self, errors: dict[str, str]) -> None:
        for key, message in errors.items():
            field = self.fields.get(key)
            label = self.field_errors.get(key)
            if field and label:
                field.setProperty("invalid", True)
                field.style().unpolish(field)
                field.style().polish(field)
                label.setText(message)
                label.show()

    @staticmethod
    def _set_password_visibility(field: QLineEdit, toggle: QPushButton, visible: bool) -> None:
        field.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        toggle.setText("Hide" if visible else "Show")
        toggle.setAccessibleName("Hide password" if visible else "Show password")


class LoginPage(AuthPage):
    def __init__(self) -> None:
        super().__init__("Sign in", "Use your PhishReport account to continue.")
        email = self.add_field("email", "Email address")
        email.setInputMethodHints(Qt.InputMethodHint.ImhEmailCharactersOnly)
        email.setProperty("autocomplete", "email")
        password = self.add_field("password", "Password", password=True)
        password.setProperty("autocomplete", "current-password")
        self.add_notice()
        self.add_spacer_link("Forgot password?", "forgot")
        self.add_submit("Sign in", "login")
        self.submit_button.setProperty("normalText", "Sign in")
        self.layout.addSpacing(22)
        self.add_link("New to PhishReport?", "Create an account", "signup")


class SignupPage(AuthPage):
    def __init__(self) -> None:
        super().__init__(
            "Create your account",
            "One account to help you assess suspicious messages.",
        )
        self.add_notice()
        email = self.add_field("email", "Email address")
        email.setInputMethodHints(Qt.InputMethodHint.ImhEmailCharactersOnly)
        self.add_field(
            "password",
            "Password",
            password=True,
            hint=f"Use at least {PASSWORD_MIN_LENGTH} characters.",
        )
        self.add_field("confirmPassword", "Confirm password", password=True)
        self.add_submit("Create account", "signup")
        self.submit_button.setProperty("normalText", "Create account")
        self.layout.addSpacing(18)
        self.add_link("Already have an account?", "Sign in", "login")


class ForgotPasswordPage(AuthPage):
    def __init__(self) -> None:
        super().__init__(
            "Reset your password",
            "Enter your account email and we’ll send reset instructions if an account matches.",
        )
        self.add_notice()
        email = self.add_field("email", "Email address")
        email.setInputMethodHints(Qt.InputMethodHint.ImhEmailCharactersOnly)
        self.add_submit("Send reset instructions", "forgot")
        self.submit_button.setProperty("normalText", "Send reset instructions")
        self.layout.addSpacing(18)
        self.add_link("Remembered your password?", "Sign in", "login")


class ResetPasswordPage(AuthPage):
    def __init__(self, token: str) -> None:
        super().__init__(
            "Choose a new password",
            f"Use at least {PASSWORD_MIN_LENGTH} characters for your new password.",
        )
        self.token = token
        self.add_notice()
        self.add_field("password", "New password", password=True)
        self.add_field("confirmPassword", "Confirm new password", password=True)
        self.add_submit("Update password", "reset")
        self.submit_button.setProperty("normalText", "Update password")
        self.layout.addSpacing(18)
        self.add_link("Changed your mind?", "Sign in", "login")

    def values(self) -> dict[str, str]:
        values = super().values()
        values["token"] = self.token
        return values


class MainWindow(QMainWindow):
    def __init__(
        self,
        api: AuthApiClient | None = None,
        reset_token: str = "",
        check_session: bool = True,
    ) -> None:
        super().__init__()
        self.api = api or AuthApiClient()
        self._workers: dict[
            ApiWorker, tuple[Callable[[Any], None], Callable[[AuthApiError], None]]
        ] = {}
        self._user: dict[str, str] | None = None
        self._close_requested = False

        self.setWindowTitle("PhishReport")
        self.setMinimumSize(760, 560)
        self.resize(1040, 700)

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

        self.pages = QStackedWidget()
        self.pages.setContentsMargins(0, 0, 0, 0)
        self.page_layout = QVBoxLayout()
        page_host = QWidget()
        page_host.setLayout(self.page_layout)
        self.page_layout.setContentsMargins(76, 48, 76, 44)
        self.page_layout.addStretch(1)
        self.stack = QStackedWidget()
        self.page_layout.addWidget(self.stack)
        self.page_layout.addStretch(1)
        self.pages.addWidget(page_host)

        self.auth_pages: dict[str, AuthPage] = {
            "login": LoginPage(),
            "signup": SignupPage(),
            "forgot": ForgotPasswordPage(),
        }
        for key, page in self.auth_pages.items():
            page.navigate.connect(self.show_page)
            page.submit.connect(self.handle_submit)
            self.stack.addWidget(page)
            page.setProperty("route", key)

        self.reset_page = (
            ResetPasswordPage(reset_token) if reset_token else None
        )
        if self.reset_page:
            self.reset_page.navigate.connect(self.show_page)
            self.reset_page.submit.connect(self.handle_submit)
            self.stack.addWidget(self.reset_page)

        root_layout.addWidget(self.brand_panel, 9)
        root_layout.addWidget(self.pages, 11)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLESHEET)
        self.show_page("reset" if reset_token else "login")

        if check_session:
            self._run_api(
                self.api.current_user, self._restore_session, self._session_unavailable
            )

    def show_page(self, route: str) -> None:
        routes = {"login": 0, "signup": 1, "forgot": 2}
        if route == "reset" and self.reset_page:
            self.stack.setCurrentWidget(self.reset_page)
            self.reset_page.setFocus()
            return
        self.stack.setCurrentIndex(routes.get(route, 0))
        page = self.auth_pages.get(route)
        if page:
            page.clear_notice()
            first_field = next(iter(page.fields.values()), None)
            if first_field:
                first_field.setFocus(Qt.FocusReason.OtherFocusReason)

    def handle_submit(self, action: str, values: dict[str, str]) -> None:
        page = self.stack.currentWidget()
        if not isinstance(page, AuthPage):
            return
        page.clear_notice()

        email = values.get("email", "").strip()
        password = values.get("password", "")
        if action in ("login", "signup", "forgot") and not self._valid_email(email):
            page.show_field_errors({"email": "Enter a valid email address."})
            return
        if action in ("signup", "reset") and len(password) < PASSWORD_MIN_LENGTH:
            page.show_field_errors(
                {"password": f"Use at least {PASSWORD_MIN_LENGTH} characters."}
            )
            return
        if action == "login" and not password:
            page.show_field_errors({"password": "Enter your password."})
            return
        if action in ("signup", "reset") and password != values.get("confirmPassword"):
            page.show_field_errors({"confirmPassword": "Passwords do not match."})
            return

        if action == "login":
            operation = partial(self.api.sign_in, email, password)
            success = self._signed_in
            busy_label = "Signing in…"
        elif action == "signup":
            operation = partial(self.api.create_account, email, password)
            success = self._account_created
            busy_label = "Creating account…"
        elif action == "forgot":
            operation = partial(self.api.request_password_reset, email)
            success = self._reset_requested
            busy_label = "Sending instructions…"
        else:
            operation = partial(self.api.reset_password, values["token"], password)
            success = self._password_reset
            busy_label = "Updating password…"

        page.set_busy(True, busy_label)
        self._run_api(
            operation,
            partial(self._handle_page_success, page, success),
            partial(self._handle_page_failure, page),
        )

    def _run_api(
        self,
        operation: Callable[[], Any],
        success: Callable[[Any], None],
        failure: Callable[[AuthApiError], None],
    ) -> None:
        worker = ApiWorker(operation)
        self._workers[worker] = (success, failure)
        worker.succeeded.connect(self._handle_worker_success)
        worker.failed.connect(self._handle_worker_failure)
        worker.finished.connect(self._clear_finished_worker)
        worker.start()

    @Slot(object)
    def _handle_worker_success(self, result: Any) -> None:
        worker = self.sender()
        if worker in self._workers:
            success, _failure = self._workers[worker]
            success(result)

    @Slot(object)
    def _handle_worker_failure(self, error: AuthApiError) -> None:
        worker = self.sender()
        if worker in self._workers:
            _success, failure = self._workers[worker]
            failure(error)

    @staticmethod
    def _handle_page_success(
        page: AuthPage, callback: Callable[[Any], None], result: Any
    ) -> None:
        page.set_busy(False)
        callback(result)

    @staticmethod
    def _handle_page_failure(page: AuthPage, error: AuthApiError) -> None:
        page.set_busy(False)
        page.set_notice(str(error))
        page.show_field_errors(error.field_errors)

    @Slot()
    def _clear_finished_worker(self) -> None:
        worker = self.sender()
        self._workers.pop(worker, None)
        worker.deleteLater()
        if self._close_requested and not self._workers:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._workers:
            self._close_requested = True
            self.statusBar().showMessage("Finishing the current request before closing…")
            event.ignore()
            return
        event.accept()

    def _restore_session(self, user: dict[str, str]) -> None:
        self._signed_in(user)

    def _session_unavailable(self, error: AuthApiError) -> None:
        if error.status == 401:
            return
        page = self.auth_pages["login"]
        page.set_notice(str(error), "info")

    def _signed_in(self, user: dict[str, str]) -> None:
        self._user = user
        if hasattr(self, "account_page"):
            self.stack.removeWidget(self.account_page)
            self.account_page.deleteLater()
        self.account_page = self._build_account_page(user)
        self.stack.addWidget(self.account_page)
        self.stack.setCurrentWidget(self.account_page)

    def _account_created(self, result: dict[str, Any]) -> None:
        if result["verificationRequired"]:
            self.show_page("signup")
            self.auth_pages["signup"].set_notice(
                "If an account can be created, check your inbox for "
                "instructions to verify this email.",
                "success",
            )
        else:
            self._signed_in(result["user"])

    def _reset_requested(self, _result: Any) -> None:
        page = self.auth_pages["forgot"]
        page.set_notice(
            "If an account matches that email, reset instructions will be sent.",
            "success",
        )

    def _password_reset(self, _result: Any) -> None:
        self.show_page("login")
        self.auth_pages["login"].set_notice(
            "Your password was updated. Sign in with your new password.",
            "success",
        )

    def _build_account_page(self, user: dict[str, str]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        title = QLabel("You’re signed in")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        email = QLabel(user["email"])
        email.setObjectName("intro")
        email.setContentsMargins(0, 10, 0, 18)
        layout.addWidget(email)
        note = QLabel(
            "Your PhishReport workspace will be connected here in a later phase."
        )
        note.setObjectName("intro")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.account_notice = QLabel()
        self.account_notice.setObjectName("notice")
        self.account_notice.setProperty("severity", "error")
        self.account_notice.setWordWrap(True)
        self.account_notice.hide()
        layout.addWidget(self.account_notice)
        layout.addSpacing(20)
        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_button.clicked.connect(self._sign_out)
        layout.addWidget(self.sign_out_button)
        layout.addStretch(1)
        return page

    def _sign_out(self) -> None:
        self.sign_out_button.setEnabled(False)
        self.sign_out_button.setText("Signing out…")
        self._run_api(
            self.api.sign_out,
            lambda _result: self._signed_out(),
            lambda error: self._account_sign_out_failed(error),
        )

    def _signed_out(self) -> None:
        self._user = None
        self.show_page("login")

    def _account_sign_out_failed(self, error: AuthApiError) -> None:
        self.sign_out_button.setEnabled(True)
        self.sign_out_button.setText("Sign out")
        self.account_notice.setText(str(error))
        self.account_notice.show()

    @staticmethod
    def _valid_email(email: str) -> bool:
        local, separator, domain = email.partition("@")
        return bool(
            separator
            and local
            and "." in domain
            and not domain.endswith(".")
            and not any(character.isspace() for character in email)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PhishReport desktop authentication GUI.")
    parser.add_argument(
        "--reset-token",
        default=os.environ.get("PHISHREPORT_RESET_TOKEN", ""),
        help="Open the password-reset screen for a token supplied by the backend.",
    )
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("PhishReport")
    app.setStyle("Fusion")
    window = MainWindow(reset_token=args.reset_token)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
