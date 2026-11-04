"""Public launcher and compatibility exports for the desktop GUI."""

from app_gui.main_window import MainWindow, main

__all__ = ["MainWindow", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
