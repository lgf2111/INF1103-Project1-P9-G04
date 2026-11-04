"""Concrete authentication pages."""

from __future__ import annotations

from PySide6.QtCore import Qt

from app_gui.ui.auth_form import PASSWORD_MIN_LENGTH, AuthPage


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
