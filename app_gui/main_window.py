"""Main-window controller for the PhishReport desktop GUI."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from app_gui.auth_api import AuthApiClient, AuthApiError
from app_gui.ui.auth_pages import PASSWORD_MIN_LENGTH, AuthPage
from app_gui.ui.auth_shell import AuthShell
from app_gui.ui.dashboard import DashboardShell
from app_gui.ui.styles import STYLESHEET
from app_gui.ui.workers import ApiWorker


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

        self.auth_shell = AuthShell(reset_token)
        self.auth_root = self.auth_shell.widget
        self.auth_pages = self.auth_shell.auth_pages
        self.stack = self.auth_shell.stack
        self.reset_page = self.auth_shell.reset_page
        for key, page in self.auth_pages.items():
            page.navigate.connect(self.show_page)
            page.submit.connect(self.handle_submit)
        if self.reset_page:
            self.reset_page.navigate.connect(self.show_page)
            self.reset_page.submit.connect(self.handle_submit)

        dashboard = DashboardShell(self._sign_out)
        self.dashboard = dashboard
        self.dashboard_shell = dashboard.widget
        self.profile_button = dashboard.profile_button
        self.profile_menu = dashboard.profile_menu
        self.profile_identity_action = dashboard.profile_identity_action
        self.profile_email_action = dashboard.profile_email_action
        self.settings_action = dashboard.settings_action
        self.sign_out_action = dashboard.sign_out_action
        self.account_notice = dashboard.account_notice
        self.app_pages = dashboard.app_pages
        self.dashboard_page = dashboard.dashboard_page
        self.settings_page = dashboard.settings_page

        self.root_stack = QStackedWidget()
        self.root_stack.addWidget(self.auth_root)
        self.root_stack.addWidget(self.dashboard_shell)
        self.setCentralWidget(self.root_stack)
        self.setStyleSheet(STYLESHEET)
        self.show_page("reset" if reset_token else "login")

        if check_session:
            self._run_api(self.api.current_user, self._restore_session, self._session_unavailable)

    def show_page(self, route: str) -> None:
        routes = {"login": 0, "signup": 1, "forgot": 2}
        self.root_stack.setCurrentWidget(self.auth_root)
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
            page.show_field_errors({"password": f"Use at least {PASSWORD_MIN_LENGTH} characters."})
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
    def _handle_page_success(page: AuthPage, callback: Callable[[Any], None], result: Any) -> None:
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
        name = user.get("name", "").strip()
        self.profile_button.setText(self._user_initials(name or user["email"]))
        self.profile_button.setAccessibleName(f"Account menu for {name or user['email']}")
        self.profile_identity_action.setText(name or "Your account")
        self.profile_email_action.setText(user["email"])
        self.account_notice.hide()
        self.app_pages.setCurrentWidget(self.dashboard_page)
        self.root_stack.setCurrentWidget(self.dashboard_shell)

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

    def _sign_out(self) -> None:
        self.sign_out_action.setEnabled(False)
        self.sign_out_action.setText("Signing out…")
        self._run_api(
            self.api.sign_out,
            lambda _result: self._signed_out(),
            lambda error: self._account_sign_out_failed(error),
        )

    def _signed_out(self) -> None:
        self._user = None
        self.sign_out_action.setEnabled(True)
        self.sign_out_action.setText("Sign out")
        self.show_page("login")

    def _account_sign_out_failed(self, error: AuthApiError) -> None:
        self.sign_out_action.setEnabled(True)
        self.sign_out_action.setText("Sign out")
        self.account_notice.setText(str(error))
        self.account_notice.show()

    @staticmethod
    def _user_initials(name_or_email: str) -> str:
        words = name_or_email.split()
        if len(words) == 1 and "@" in words[0]:
            words = [words[0].split("@", 1)[0]]
        initials = "".join(word[0] for word in words[:2] if word)
        return initials.upper() or "P"

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
