# Make app/ modules available to offline tests, matching the CLI entry point.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))


def pytest_configure(config):
    """Register the short feature showcase separately from regression checks."""
    config.addinivalue_line("markers", "demo: concise automated feature showcase")
