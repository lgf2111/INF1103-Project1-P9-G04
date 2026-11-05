import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app_gui.auth_api import AuthApiError
from app_gui.main import MainWindow


class FakeApi:
    def __init__(self):
        self.login_calls = []
        self.signup_calls = []
        self.sign_out_calls = 0

    def current_user(self):
        raise AuthApiError("Sign in required.", 401)

    def sign_in(self, email, password):
        self.login_calls.append((email, password))
        return {"id": "user-1", "email": email}

    def create_account(self, email, password):
        self.signup_calls.append((email, password))
        return {"verificationRequired": True, "user": None}

    def request_password_reset(self, _email):
        return None

    def reset_password(self, _token, _password):
        return None

    def sign_out(self):
        self.sign_out_calls += 1


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    instance = QApplication.instance() or QApplication([])
    yield instance


def make_window():
    api = FakeApi()
    window = MainWindow(api=api, check_session=False)
    window.show()
    return window, api


def test_login_screen_has_expected_fields_and_navigation(app):
    window, _api = make_window()
    try:
        assert window.windowTitle() == "PhishReport"
        assert window.auth_pages["login"].fields["email"].accessibleName() == "Email address"
        assert window.auth_pages["login"].fields["password"].echoMode().name == "Password"
        password_toggle = window.auth_pages["login"].findChild(
            QPushButton, "passwordToggle"
        )
        assert password_toggle is not None
        assert password_toggle.accessibleName() == "Show password"
        password_toggle.click()
        assert window.auth_pages["login"].fields["password"].echoMode().name == "Normal"
        links = window.auth_pages["login"].findChildren(QPushButton, "textButton")
        assert {link.text() for link in links} == {"Forgot password?", "Create an account"}
        login_page = window.auth_pages["login"]
        forgot_link = next(link for link in links if link.text() == "Forgot password?")
        assert login_page.form.indexOf(forgot_link) < login_page.form.indexOf(
            login_page.submit_button
        )
        assert login_page.footer.itemAt(0).spacerItem() is not None
        assert login_page.footer.itemAt(login_page.footer.count() - 1).spacerItem() is not None
        prefix = next(
            label
            for label in login_page.footer.parentWidget().findChildren(QLabel)
            if label.text() == "New to PhishReport?"
        )
        create_account = next(link for link in links if link.text() == "Create an account")
        group_center = (prefix.geometry().left() + create_account.geometry().right()) / 2
        assert abs(group_center - login_page.footer.geometry().center().x()) <= 3
    finally:
        window.close()


def test_invalid_email_is_rejected_before_backend_call(app):
    window, api = make_window()
    try:
        window.handle_submit("login", {"email": "not-an-email", "password": "secret"})

        assert api.login_calls == []
        error = window.auth_pages["login"].field_errors["email"]
        assert error.text() == "Enter a valid email address."
        assert window.auth_pages["login"].fields["email"].property("invalid") is True
    finally:
        window.close()


def test_signup_password_mismatch_is_rejected_before_backend_call(app):
    window, api = make_window()
    try:
        window.show_page("signup")
        window.handle_submit(
            "signup",
            {
                "email": "person@example.com",
                "password": "long-enough-password",
                "confirmPassword": "different-password",
            },
        )

        assert api.signup_calls == []
        assert (
            window.auth_pages["signup"].field_errors["confirmPassword"].text()
            == "Passwords do not match."
        )
    finally:
        window.close()


def test_login_uses_background_request_and_preserves_password_whitespace(app):
    window, api = make_window()
    password = "  password with edges  "
    try:
        window.handle_submit(
            "login",
            {"email": " person@example.com ", "password": password},
        )

        for _ in range(20):
            QTest.qWait(25)
            if window._user is not None:
                break

        assert api.login_calls == [("person@example.com", password)]
        assert window._user == {"id": "user-1", "email": "person@example.com"}
        assert window.root_stack.currentWidget() is window.dashboard_shell
        assert window.app_pages.currentWidget() is window.dashboard_page
        assert window.profile_button.text() == "P"
    finally:
        window.close()


def test_login_rejects_empty_password_before_backend_call(app):
    window, api = make_window()
    try:
        window.handle_submit("login", {"email": "person@example.com", "password": ""})

        assert api.login_calls == []
        assert window.auth_pages["login"].field_errors["password"].text() == (
            "Enter your password."
        )
    finally:
        window.close()


def test_profile_menu_opens_locked_settings_and_returns_to_overview(app):
    window, _api = make_window()
    try:
        window._signed_in(
            {"id": "user-1", "email": "person@example.com", "name": "Pat Example"}
        )
        assert window.profile_button.text() == "PE"
        assert window.profile_button.accessibleName() == "Account menu for Pat Example"

        window.settings_action.trigger()
        assert window.app_pages.currentWidget() is window.settings_page
        assert any(
            label.text() == "Settings are locked"
            for label in window.settings_page.findChildren(QLabel)
        )

        back_button = next(
            button
            for button in window.settings_page.findChildren(QPushButton)
            if button.text() == "Back to overview"
        )
        back_button.click()
        assert window.app_pages.currentWidget() is window.dashboard_page
    finally:
        window.close()


def test_profile_menu_sign_out_returns_to_login(app):
    window, api = make_window()
    try:
        window._signed_in({"id": "user-1", "email": "person@example.com"})
        window.sign_out_action.trigger()

        for _ in range(20):
            QTest.qWait(25)
            if window._user is None:
                break

        assert api.sign_out_calls == 1
        assert window._user is None
        assert window.root_stack.currentWidget() is window.auth_root
        assert window.stack.currentWidget() is window.auth_pages["login"]
    finally:
        window.close()
