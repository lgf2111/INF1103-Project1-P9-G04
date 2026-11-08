"""Class-based I/O Manager entry point.

Console input, display and email-file handling live in ``phishreport.io``.
This module exposes ``IOManager`` as the public manager class.
"""

from phishreport.io import IOManager

__all__ = ["IOManager"]
