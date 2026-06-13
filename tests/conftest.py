"""Shared test configuration.

Makes the separate ``server/`` package importable without installing it, so
the sync end-to-end tests can spin up a real server in-process.
"""

import os
import sys

_SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)
