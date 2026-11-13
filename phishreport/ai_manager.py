"""Compatibility interface for the class-based AI Manager package.

Assessment logic lives in the ``phishreport.ai`` package; this module exposes
``AIManager`` so the manager-file contract is met without procedural wrappers.
"""

from phishreport.ai import AIManager

__all__ = ["AIManager"]
