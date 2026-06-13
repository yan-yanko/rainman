"""
Actor identity
==============

Who is performing an action (creating a memory, recalling, forgetting).
Single-machine, single-developer today — identity is the local OS user,
overridable via ``RAINMAN_AUTHOR`` (e.g. a CI bot name, or a per-seat id once
the team sync server exists). Zero external calls.
"""

import getpass
import os


def current_actor() -> str:
    """Best-effort identity of the current actor.

    Precedence: ``RAINMAN_AUTHOR`` env var > OS login name > "unknown".
    Never raises — identity must never block a memory write.
    """
    override = os.environ.get("RAINMAN_AUTHOR", "").strip()
    if override:
        return override[:100]
    try:
        return (getpass.getuser() or "unknown")[:100]
    except Exception:
        return "unknown"
