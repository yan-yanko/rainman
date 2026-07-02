"""Working memory — a small, capacity-limited, session-scoped active set.

Human memory has a limited-capacity buffer (~7±2 items; Miller / Baddeley) that
holds what is *currently in mind*, distinct from the vast long-term store. Recall
in Rainman is otherwise stateless — it re-scores the whole store each call. This
adds the missing buffer: the memories most recently surfaced THIS session stay
"warm" in a tiny LRU that carries across turns and decays.

Design: an ordered LRU of memory ids with per-entry last-touch times, persisted
to a small JSON side file (transient session state, never committed). Capacity
bounds it; a TTL expires a stale session. Non-invasive — it records focus, it
does NOT change recall ranking. stdlib only.
"""

import json
import os

CAPACITY = 7            # Miller's 7±2 — the classic working-memory span
TTL_SECONDS = 2 * 3600  # a session idle this long is considered over


class WorkingMemory:
    """LRU buffer of memory ids, backed by a JSON file. All ops are best-effort;
    a corrupt/missing file is treated as empty (session state is disposable)."""

    def __init__(self, path: str, capacity: int = CAPACITY, ttl: float = TTL_SECONDS):
        self.path = path
        self.capacity = capacity
        self.ttl = ttl

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            return [(e["id"], float(e["ts"])) for e in entries if "id" in e and "ts" in e]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def _save(self, entries):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"entries": [{"id": i, "ts": t} for i, t in entries]}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass  # session state is disposable — never break the caller

    def touch(self, ids, now: float) -> None:
        """Bring ``ids`` to the front of the buffer (most recent first), stamping
        each with ``now``. Drops entries older than the TTL, then caps to capacity
        (evicting the least-recently-active — LRU)."""
        ids = [i for i in ids if i]
        if not ids:
            return
        keep = {i for i, t in self._load() if now - t < self.ttl and i not in ids}
        merged = [(i, now) for i in ids]  # newly-touched, front
        merged += [(i, t) for i, t in self._load() if i in keep]
        # de-dup preserving order, then cap
        seen, out = set(), []
        for i, t in merged:
            if i in seen:
                continue
            seen.add(i)
            out.append((i, t))
        self._save(out[:self.capacity])

    def active(self, now: float):
        """Ids currently in the buffer (most recent first, TTL-filtered)."""
        return [i for i, t in self._load() if now - t < self.ttl]

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except OSError:
            pass
