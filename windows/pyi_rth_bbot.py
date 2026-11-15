# PyInstaller runtime hook for BBOT on Windows
import os
import sys

# Prefer the pure-Python HTTP backend when frozen on Windows
os.environ.setdefault("BBOT_HTTP_BACKEND", "httpx")

# Disable ansible-based dependency installation (not available / not needed)
os.environ.setdefault("BBOT_DEPS_BEHAVIOR", "disable")

# Ensure multiprocessing works in frozen apps
if sys.platform == "win32":
    import multiprocessing

    multiprocessing.freeze_support()
