"""
SQLite storage backend
======================

A drop-in alternative to the JSON backend (``MemoryStore``) for scale:
WAL-mode SQLite gives real multi-process concurrency (no lockfile), no
2000-memory cap, and indexed retention/stats queries — all with stdlib
``sqlite3`` (zero external deps preserved).

One database file per layer, mirroring the JSON layout:
    <project>/.rainman/memories.db
    ~/.rainman/memories.db

Each memory is stored as its full ``to_dict()`` JSON in a ``data`` column, so
the record schema stays flexible (new fields like ``author`` need no
migration). ``timestamp`` / ``category`` / ``layer`` are denormalised into
indexed columns for retention and stats.

Scoring stays in Python — ``load_all()`` returns the working set and the
engine ranks it. Pushing filtering into SQL is a future optimisation; the
scoring engine is untouched.

NOTE: a SQLite file is not git-diffable, so the "commit .rainman/ to share"
story is JSON-only. Team sharing moves to the sync server (Phase 2b).
"""

import json
import os
import sqlite3
from typing import Dict, List, Optional

from rainman.core.models import Memory
from rainman.core.store import GLOBAL_DIR, PROJECT_DIR_NAME, SCHEMA_VERSION
from rainman.core.log import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id        TEXT PRIMARY KEY,
    data      TEXT NOT NULL,
    timestamp REAL NOT NULL,
    category  TEXT,
    layer     TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_ts  ON memories(timestamp);
CREATE INDEX IF NOT EXISTS idx_memories_cat ON memories(category);
"""


class SqliteStore:
    """Layered SQLite persistence: global + project. One DB per layer."""

    def __init__(self, project_dir: Optional[str] = None, global_dir: Optional[str] = None):
        self._global_dir = global_dir or GLOBAL_DIR
        self._project_dir = (
            os.path.join(project_dir, PROJECT_DIR_NAME) if project_dir else None
        )

    # ── Paths ────────────────────────────────────────────────────

    def _global_db(self) -> str:
        return os.path.join(self._global_dir, "memories.db")

    def _project_db(self) -> Optional[str]:
        return os.path.join(self._project_dir, "memories.db") if self._project_dir else None

    def _db_for_layer(self, layer: str) -> Optional[str]:
        if layer == "global":
            return self._global_db()
        return self._project_db() or self._global_db()

    def global_dir(self) -> str:
        return self._global_dir

    def audit_path(self) -> str:
        base = self._project_dir if self._project_dir else self._global_dir
        return os.path.join(base, "audit.log")

    # ── Connection ───────────────────────────────────────────────

    def _connect(self, path: str) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        return conn

    # ── Public API ───────────────────────────────────────────────

    def load_all(self) -> List[Memory]:
        memories: List[Memory] = []
        memories.extend(self._load_db(self._global_db(), "global"))
        pdb = self._project_db()
        if pdb:
            memories.extend(self._load_db(pdb, "project"))
        return memories

    def _load_db(self, path: str, layer: str) -> List[Memory]:
        if not os.path.exists(path):
            return []
        out: List[Memory] = []
        try:
            conn = self._connect(path)
            try:
                for (data,) in conn.execute("SELECT data FROM memories"):
                    try:
                        m = Memory.from_dict(json.loads(data))
                        m.layer = layer
                        out.append(m)
                    except (ValueError, KeyError, TypeError) as e:
                        log.warning("skipping malformed row in %s: %s", path, e)
            finally:
                conn.close()
        except sqlite3.Error as e:
            log.error("failed to read %s: %s", path, e)
        return out

    def save_all(self, memories: List[Memory]) -> None:
        # Authoritative full set: replace each layer's contents.
        self._replace_layer("global", [m for m in memories if m.layer == "global"])
        if self._project_db():
            self._replace_layer("project", [m for m in memories if m.layer == "project"])

    def save_layers(self, memories: List[Memory], layers: set) -> None:
        for layer in layers:
            if layer == "project" and not self._project_db():
                continue
            self._replace_layer(layer, [m for m in memories if m.layer == layer])

    def _replace_layer(self, layer: str, memories: List[Memory]) -> None:
        path = self._db_for_layer(layer)
        conn = self._connect(path)
        try:
            with conn:  # transaction
                conn.execute("DELETE FROM memories")
                conn.executemany(
                    "INSERT INTO memories (id, data, timestamp, category, layer) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [self._row(m, layer) for m in memories],
                )
        finally:
            conn.close()

    def save_one(self, memory: Memory) -> None:
        layer = memory.layer
        if layer == "global":
            path = self._global_db()
        elif self._project_db():
            path = self._project_db()
        else:
            memory.layer = layer = "global"
            path = self._global_db()
        conn = self._connect(path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO memories (id, data, timestamp, category, layer) "
                    "VALUES (?, ?, ?, ?, ?)",
                    self._row(memory, layer),
                )
        finally:
            conn.close()

    def update_rehearsal_stats(self, updates: Dict[str, dict], layer: str) -> None:
        path = self._db_for_layer(layer)
        if not os.path.exists(path):
            return
        conn = self._connect(path)
        try:
            with conn:
                for mid, fields in updates.items():
                    row = conn.execute(
                        "SELECT data FROM memories WHERE id = ?", (mid,)
                    ).fetchone()
                    if not row:
                        continue
                    d = json.loads(row[0])
                    d["recall_count"] = fields.get("recall_count", d.get("recall_count", 0))
                    d["last_recalled"] = fields.get("last_recalled", d.get("last_recalled"))
                    conn.execute(
                        "UPDATE memories SET data = ? WHERE id = ?",
                        (json.dumps(d), mid),
                    )
        finally:
            conn.close()

    def get_stats(self) -> Dict:
        memories = self.load_all()
        by_category: Dict[str, int] = {}
        by_layer = {"global": 0, "project": 0}
        by_sentiment: Dict[str, int] = {}
        all_tags: Dict[str, int] = {}
        for m in memories:
            by_category[m.category] = by_category.get(m.category, 0) + 1
            by_layer[m.layer] = by_layer.get(m.layer, 0) + 1
            by_sentiment[m.sentiment] = by_sentiment.get(m.sentiment, 0) + 1
            for t in m.tags:
                all_tags[t] = all_tags.get(t, 0) + 1
        return {
            "total": len(memories),
            "by_category": by_category,
            "by_layer": by_layer,
            "by_sentiment": by_sentiment,
            "top_tags": sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    def schema_version(self, layer: str = "project") -> Optional[int]:
        base = self._project_dir if layer == "project" else self._global_dir
        if not base:
            return None
        try:
            with open(os.path.join(base, "config.json"), encoding="utf-8") as f:
                return json.load(f).get("schema_version")
        except (OSError, ValueError):
            return None

    def init_project(self, project_dir: str) -> str:
        target = os.path.join(project_dir, PROJECT_DIR_NAME)
        os.makedirs(target, exist_ok=True)
        self._connect(os.path.join(target, "memories.db")).close()
        self._write_config(os.path.join(target, "config.json"), {"project": ""})
        self._project_dir = target
        return target

    def init_global(self) -> str:
        os.makedirs(self._global_dir, exist_ok=True)
        self._connect(self._global_db()).close()
        self._write_config(os.path.join(self._global_dir, "config.json"), {})
        return self._global_dir

    # ── Internal ─────────────────────────────────────────────────

    @staticmethod
    def _row(m: Memory, layer: str):
        return (m.id, json.dumps(m.to_dict()), m.timestamp, m.category, layer)

    @staticmethod
    def _write_config(path: str, extra: Dict) -> None:
        if os.path.exists(path):
            return
        config = {"version": "0.1.0", "schema_version": SCHEMA_VERSION, "storage_backend": "sqlite"}
        config.update(extra)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
