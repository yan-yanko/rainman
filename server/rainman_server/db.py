"""
Sync server storage (SQLite)
============================

Authoritative store for synced project memories. Each upsert/delete gets a
monotonically increasing ``seq`` so clients can pull "everything since my
cursor" without any clock coordination. Deletes are tombstones (``deleted=1``)
so they propagate to other clients.

Stdlib only (``sqlite3``). WAL mode for concurrent request threads. A new
connection per call keeps it thread-safe under ThreadingHTTPServer.
"""

import hashlib
import json
import os
import sqlite3
from typing import List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
INSERT OR IGNORE INTO meta(key, value) VALUES ('seq', 0);

CREATE TABLE IF NOT EXISTS tokens (
    token     TEXT PRIMARY KEY,
    username  TEXT NOT NULL,
    workspace TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    workspace    TEXT NOT NULL,
    id           TEXT NOT NULL,
    data         TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    deleted      INTEGER NOT NULL DEFAULT 0,
    seq          INTEGER NOT NULL,
    PRIMARY KEY (workspace, id)
);
CREATE INDEX IF NOT EXISTS idx_items_seq ON items(workspace, seq);
"""

# Fields excluded from the content hash: volatile per-client rehearsal stats
# shouldn't count as a "change" that forces a re-sync.
_VOLATILE = ("recall_count", "last_recalled")


def content_hash(data: dict) -> str:
    stable = {k: v for k, v in data.items() if k not in _VOLATILE}
    blob = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ServerDB:
    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _next_seq(conn: sqlite3.Connection) -> int:
        conn.execute("UPDATE meta SET value = value + 1 WHERE key = 'seq'")
        return conn.execute("SELECT value FROM meta WHERE key = 'seq'").fetchone()[0]

    # ── Tokens ───────────────────────────────────────────────────

    def add_token(self, token: str, username: str, workspace: str) -> None:
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tokens (token, username, workspace) VALUES (?, ?, ?)",
                    (token, username, workspace),
                )
        finally:
            conn.close()

    def resolve_token(self, token: str) -> Optional[Tuple[str, str]]:
        if not token:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT username, workspace FROM tokens WHERE token = ?", (token,)
            ).fetchone()
            return (row[0], row[1]) if row else None
        finally:
            conn.close()

    # ── Sync ─────────────────────────────────────────────────────

    def pull(self, workspace: str, since: int) -> Tuple[int, List[dict]]:
        """Return (cursor, changes) for everything in workspace with seq > since."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, data, deleted, seq FROM items "
                "WHERE workspace = ? AND seq > ? ORDER BY seq",
                (workspace, since),
            ).fetchall()
        finally:
            conn.close()
        cursor = since
        changes = []
        for mid, data, deleted, seq in rows:
            cursor = max(cursor, seq)
            changes.append({
                "id": mid,
                "data": None if deleted else json.loads(data),
                "deleted": bool(deleted),
                "seq": seq,
            })
        return cursor, changes

    def push(self, workspace: str, memories: List[dict], deletions: List[str],
             author: str) -> dict:
        """Upsert changed memories and tombstone deletions. Returns cursor + per-id seq."""
        conn = self._connect()
        seqs = {}
        try:
            with conn:
                for data in memories:
                    mid = data.get("id")
                    if not mid:
                        continue
                    # Server stamps the authenticated author as provenance.
                    data = {**data, "author": author or data.get("author", "")}
                    h = content_hash(data)
                    existing = conn.execute(
                        "SELECT content_hash, deleted FROM items WHERE workspace = ? AND id = ?",
                        (workspace, mid),
                    ).fetchone()
                    if existing and existing[0] == h and not existing[1]:
                        continue  # unchanged
                    seq = self._next_seq(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO items "
                        "(workspace, id, data, content_hash, deleted, seq) "
                        "VALUES (?, ?, ?, ?, 0, ?)",
                        (workspace, mid, json.dumps(data, ensure_ascii=False), h, seq),
                    )
                    seqs[mid] = seq

                for mid in deletions:
                    existing = conn.execute(
                        "SELECT deleted FROM items WHERE workspace = ? AND id = ?",
                        (workspace, mid),
                    ).fetchone()
                    if not existing or existing[0]:
                        continue  # unknown or already a tombstone
                    seq = self._next_seq(conn)
                    conn.execute(
                        "UPDATE items SET deleted = 1, seq = ?, data = '{}', content_hash = '' "
                        "WHERE workspace = ? AND id = ?",
                        (seq, workspace, mid),
                    )
                    seqs[mid] = seq

                cursor = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM items WHERE workspace = ?",
                    (workspace,),
                ).fetchone()[0]
        finally:
            conn.close()
        return {"accepted": len(seqs), "cursor": cursor, "seqs": seqs}
