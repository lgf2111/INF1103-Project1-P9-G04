"""Reusable authentication form layout and field behavior."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

PASSWORD_MIN_LENGTH = 12


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
            toggle.toggled.connect(partial(self._set_password_visibility, field, toggle))
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
            key: field.text() if key.lower().endswith("password") else field.text().strip()
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
        field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        toggle.setText("Hide" if visible else "Show")
        toggle.setAccessibleName("Hide password" if visible else "Show password")
