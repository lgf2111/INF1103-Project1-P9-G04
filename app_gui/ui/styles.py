"""Shared Qt application stylesheet."""

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
QWidget#appShell { background: #ffffff; }
QWidget#appHeader { background: #ffffff; border-bottom: 1px solid #e8e8e8; }
QLabel#appBrand { font-size: 16px; font-weight: 600; }
QPushButton#profileButton {
    min-width: 40px;
    max-width: 40px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    border: 0;
    border-radius: 20px;
    background: #e8edf2;
    color: #202a35;
    font-weight: 600;
}
QPushButton#profileButton:hover { background: #dce3ea; }
QMenu {
    background: #ffffff;
    border: 1px solid #d7dbe0;
    padding: 5px;
}
QMenu::item { min-height: 32px; padding: 0 12px; }
QMenu::item:selected { background: #f2f4f7; }
QMenu::item:disabled { color: #555b63; }
QWidget#appCanvas { background: #ffffff; }
QFrame#emptyPanel {
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    background: #ffffff;
}
QLabel#panelTitle { font-size: 16px; font-weight: 500; }
QLabel#lockedTitle { font-size: 18px; font-weight: 500; }
"""
