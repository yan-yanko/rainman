"""
Append-only audit log
======================

Records store / recall / forget events with actor + timestamp, so an
enterprise can answer "who taught the AI this?" and "what was injected into a
model's context during that incident?". Append-only JSONL — never rewritten,
never compacted in place.

Opt-in. Off by default to preserve the zero-overhead local-dev feel; enabled
via the ``RAINMAN_AUDIT`` env var today (org policy wires this in Phase 1c).
Recall is the hot path, so events are buffered in memory and flushed in
batches (and at process exit), keeping the common case I/O-free.

Zero external deps. Writes use O_APPEND, which is atomic for the small JSONL
lines we emit, so concurrent writers (hooks + MCP server) interleave cleanly
without a separate lock.
"""

import atexit
import json
import os
import time
from typing import List, Optional

from rainman.core.log import get_logger

log = get_logger(__name__)

# Flush when this many events accumulate (also flushed at process exit).
BUFFER_LIMIT = 50


def audit_enabled() -> bool:
    """Whether auditing is on. Phase 1c will fold org policy in here."""
    return os.environ.get("RAINMAN_AUDIT", "").strip().lower() in ("1", "true", "yes", "on")


class AuditLogger:
    """Buffered, append-only JSONL audit writer."""

    def __init__(self, path: Optional[str], enabled: Optional[bool] = None,
                 buffer_limit: int = BUFFER_LIMIT):
        self._path = path
        self._enabled = audit_enabled() if enabled is None else enabled
        self._buffer_limit = buffer_limit
        self._buf: List[dict] = []
        self._registered = False

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._path)

    def record(self, event: str, actor: str, memory_ids: Optional[List[str]] = None,
               source: Optional[str] = None, **extra) -> None:
        """Buffer an audit event. No-op when auditing is off."""
        if not self.enabled:
            return
        entry = {
            "ts": time.time(),
            "event": event,
            "actor": actor,
            "memory_ids": memory_ids or [],
        }
        if source is not None:
            entry["source"] = source
        if extra:
            entry.update(extra)
        self._buf.append(entry)

        if not self._registered:
            atexit.register(self.flush)
            self._registered = True

        if len(self._buf) >= self._buffer_limit:
            self.flush()

    def flush(self) -> None:
        """Append buffered events to the log as JSONL. Never raises."""
        if not self._buf or not self._path:
            return
        batch, self._buf = self._buf, []
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                for entry in batch:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # Auditing must never break a memory operation; log and move on.
            log.error("failed to write audit log %s: %s", self._path, e)
