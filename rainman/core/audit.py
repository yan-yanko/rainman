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

Tamper evidence: every record carries ``h`` — a SHA-256 over the previous
record's ``h`` plus this record's canonical JSON — forming a hash chain.
Editing or deleting a mid-file record breaks every verification from that
point on; ``verify_chain()`` (surfaced as ``rainman audit verify``) walks the
file and reports the first broken link. Records written before this feature
have no ``h`` and are reported as legacy, not failures. (Truncating the tail
is out of scope for a local file — anchoring the head hash externally is the
sync server's job.)
"""

import atexit
import hashlib
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
        self._last_h: Optional[str] = None  # None = not yet read from disk

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

    def _init_chain(self) -> None:
        """Resume the hash chain from the last record already on disk.

        A legacy tail record (no ``h``) restarts the chain from "" — exactly
        what verify_chain() expects when it encounters a legacy record.
        """
        self._last_h = ""
        try:
            with open(self._path, "rb") as f:
                last = b""
                for line in f:
                    if line.strip():
                        last = line
            if last:
                self._last_h = json.loads(last.decode("utf-8")).get("h", "")
        except (OSError, ValueError):
            self._last_h = ""

    def flush(self) -> None:
        """Append buffered events to the log as JSONL. Never raises."""
        if not self._buf or not self._path:
            return
        batch, self._buf = self._buf, []
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if self._last_h is None:
                self._init_chain()
            with open(self._path, "a", encoding="utf-8") as f:
                for entry in batch:
                    self._last_h = _link_hash(self._last_h, entry)
                    entry = {**entry, "h": self._last_h}
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # Auditing must never break a memory operation; log and move on.
            log.error("failed to write audit log %s: %s", self._path, e)


def _link_hash(prev_h: str, entry: dict) -> str:
    """Chain link: SHA-256 of the previous hash + this record's canonical JSON."""
    body = {k: v for k, v in entry.items() if k != "h"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((prev_h + "\n" + canonical).encode("utf-8")).hexdigest()


def verify_chain(path: str) -> dict:
    """Walk an audit log and verify its hash chain.

    Returns {path, total, hashed, legacy, ok, first_bad_line} where
    ``first_bad_line`` is the 1-based line number of the first record whose
    hash does not match (None when the chain holds). Legacy records (written
    before chaining) are counted separately and reset the chain, mirroring
    how the writer resumes after them.
    """
    total = hashed = legacy = 0
    first_bad = None
    prev_h = ""
    try:
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                total += 1
                try:
                    rec = json.loads(line)
                except ValueError:
                    if first_bad is None:
                        first_bad = lineno
                    continue
                if "h" not in rec:
                    legacy += 1
                    prev_h = ""
                    continue
                hashed += 1
                if rec["h"] != _link_hash(prev_h, rec) and first_bad is None:
                    first_bad = lineno
                prev_h = rec["h"]
    except OSError:
        return {"path": path, "total": 0, "hashed": 0, "legacy": 0,
                "ok": True, "first_bad_line": None, "missing": True}
    return {"path": path, "total": total, "hashed": hashed, "legacy": legacy,
            "ok": first_bad is None, "first_bad_line": first_bad, "missing": False}
