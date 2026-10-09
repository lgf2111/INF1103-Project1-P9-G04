# Lets the tests find the code in the app/ folder.
# pytest loads this file automatically before running tests.
#
# Layers that have been restructured into their own folder (e.g. ai_manager)
# are Python packages under app/, so adding app/ to the path is enough for both
# flat modules (io_manager.py) and packages (ai_manager/) to import.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))
