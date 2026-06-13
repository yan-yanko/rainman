"""
Structured logging
===================

A thin wrapper over stdlib ``logging`` (zero external deps). All Rainman
components log through ``get_logger(__name__)`` instead of ad-hoc
``print(..., file=sys.stderr)`` so output is consistently formatted,
level-filterable, and never pollutes stdout — which on MCP/hook paths is a
protocol channel.

Level is controlled by the ``RAINMAN_LOG_LEVEL`` env var (default WARNING).
"""

import logging
import os
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to stderr with a consistent format."""
    global _CONFIGURED
    if not _CONFIGURED:
        level_name = os.environ.get("RAINMAN_LOG_LEVEL", "WARNING").upper()
        level = getattr(logging, level_name, logging.WARNING)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("[rainman] %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger("rainman")
        # Avoid duplicate handlers if reconfigured in the same process.
        if not root.handlers:
            root.addHandler(handler)
        root.setLevel(level)
        root.propagate = False
        _CONFIGURED = True

    if not name.startswith("rainman"):
        name = f"rainman.{name}"
    return logging.getLogger(name)
