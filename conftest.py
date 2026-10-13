# Make app/ modules available to offline tests, matching the CLI entry point.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
