"""Process stdio encoding safety.

On Windows, ``sys.stdout`` / ``sys.stderr`` default to the legacy cp1252 codec,
which cannot encode most non-ASCII characters (Hebrew text, the "→" arrow used
in injected context, etc.). Any ``print()`` of such content raises
``UnicodeEncodeError`` and kills the process. In practice that meant:

  * SessionStart/PostCompact hooks crashed with a non-zero exit — surfaced by
    Claude Code as a "startup hook error", and silently dropping the injected
    project-memory context.
  * ``rainman recall`` / ``status`` / ``links`` / ``context`` crashed whenever a
    matched memory contained non-ASCII content.

Reconfiguring the streams to UTF-8 makes stdio encoding-safe on every platform.
On POSIX (already UTF-8) it is a harmless no-op. ``errors="replace"`` is a
belt-and-suspenders fallback for un-encodable code points (e.g. lone
surrogates) so output degrades to "?" instead of crashing. stdlib only.
"""

import sys


def ensure_utf8_io() -> None:
    """Force UTF-8 (with replacement fallback) on stdout/stderr. Idempotent."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # Python < 3.7 or a wrapped stream that can't reconfigure.
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass  # Detached/closed stream — nothing safe to do.
