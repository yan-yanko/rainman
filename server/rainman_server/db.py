"""
Sync server storage (SQLite)
============================

Authoritative store for synced project memories. Each upsert/delete gets a
monotonically increasing ``seq`` so clients can pull "everything since my
cursor" without any clock coordination. Deletes are tombstones (``deleted=1``)
so they propagate to other clients.

Phase 3 adds RBAC (a ``role`` per token: reader < contributor < admin) and a
centralized, append-only server-side audit trail of push / pull / admin events.

Stdlib only (``sqlite3``). WAL mode for concurrent request threads. A new
connection per call keeps it thread-safe under ThreadingHTTPServer.
"""

import hashlib
import json
import os
import secrets
import time
from typing import List, Optional, Tuple

from rainman_server.crypto import seal, unseal

# Role hierarchy. Higher rank == more capability.
ROLE_READER = "reader"
ROLE_CONTRIBUTOR = "contributor"
ROLE_ADMIN = "admin"
ROLE_RANK = {ROLE_READER: 1, ROLE_CONTRIBUTOR: 2, ROLE_ADMIN: 3}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
INSERT OR IGNORE INTO meta(key, value) VALUES ('seq', 0);

CREATE TABLE IF NOT EXISTS tokens (
    token     TEXT PRIMARY KEY,
    username  TEXT NOT NULL,
    workspace TEXT NOT NULL,
    role      TEXT NOT NULL DEFAULT 'contributor'
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

CREATE TABLE IF NOT EXISTS audit (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    workspace TEXT NOT NULL,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    detail    TEXT,
    row_hash  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ws ON audit(workspace, id);
"""


def token_digest(token: str) -> str:
    """SHA-256 of a bearer token. Tokens are stored/looked up by digest only,
    never in cleartext, so a leaked DB file cannot be used to impersonate users.
    SHA-256 (not a slow KDF) is correct here: tokens are 192-bit random secrets,
    so there is no low-entropy value to brute-force and lookups stay indexed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_sha256_hex(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _audit_row_hash(prev: str, ts: float, workspace: str, actor: str,
                    action: str, detail: str) -> str:
    """Tamper-evident chain link: hash of the previous link + this row's fields.
    Altering or deleting any past row breaks every subsequent hash."""
    payload = f"{prev}|{ts!r}|{workspace}|{actor}|{action}|{detail}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
            self._migrate(conn)
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _migrate(conn) -> None:
        # Old token DBs (pre-RBAC) lack the role column — add it, defaulting to
        # contributor (the pre-RBAC behavior: any valid token could push+pull).
        token_cols = {row[1] for row in conn.execute("PRAGMA table_info(tokens)")}
        if "role" not in token_cols:
            conn.execute(
                "ALTER TABLE tokens ADD COLUMN role TEXT NOT NULL DEFAULT 'contributor'"
            )

        # Pre-hashing DBs stored raw tokens — hash them in place (idempotent:
        # already-hashed 64-hex values are left alone). After this, no cleartext
        # token is ever at rest and previously-issued tokens keep working.
        for (tok,) in conn.execute("SELECT token FROM tokens").fetchall():
            if not _is_sha256_hex(tok):
                conn.execute("UPDATE tokens SET token = ? WHERE token = ?",
                             (token_digest(tok), tok))

        # Tamper-evidence: add row_hash and backfill the chain for any existing
        # audit rows so verification covers the whole history.
        audit_cols = {row[1] for row in conn.execute("PRAGMA table_info(audit)")}
        if "row_hash" not in audit_cols:
            conn.execute("ALTER TABLE audit ADD COLUMN row_hash TEXT")
        if conn.execute("SELECT COUNT(*) FROM audit WHERE row_hash IS NULL").fetchone()[0]:
            prev = ""
            for rid, ts, ws, actor, action, detail in conn.execute(
                "SELECT id, ts, workspace, actor, action, detail FROM audit ORDER BY id"
            ).fetchall():
                prev = _audit_row_hash(prev, ts, ws, actor, action, detail or "")
                conn.execute("UPDATE audit SET row_hash = ? WHERE id = ?", (prev, rid))

    @staticmethod
    def _next_seq(conn) -> int:
        conn.execute("UPDATE meta SET value = value + 1 WHERE key = 'seq'")
        return conn.execute("SELECT value FROM meta WHERE key = 'seq'").fetchone()[0]

    # ── Tokens / RBAC ────────────────────────────────────────────

    def add_token(self, token: str, username: str, workspace: str,
                  role: str = ROLE_CONTRIBUTOR) -> None:
        if role not in ROLE_RANK:
            raise ValueError(f"unknown role: {role}")
        conn = self._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tokens (token, username, workspace, role) "
                    "VALUES (?, ?, ?, ?)",
                    (token_digest(token), username, workspace, role),
                )
        finally:
            conn.close()

    def create_token(self, username: str, workspace: str, role: str) -> str:
        """Mint a random token and store it. Returns the token (shown once)."""
        token = secrets.token_hex(24)
        self.add_token(token, username, workspace, role)
        return token

    def resolve_token(self, token: str) -> Optional[Tuple[str, str, str]]:
        """Return (username, workspace, role) or None."""
        if not token:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT username, workspace, role FROM tokens WHERE token = ?",
                (token_digest(token),),
            ).fetchone()
            return (row[0], row[1], row[2]) if row else None
        finally:
            conn.close()

    def list_users(self, workspace: str) -> List[dict]:
        """Distinct users in a workspace with their highest role (no secrets)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT username, role FROM tokens WHERE workspace = ?", (workspace,)
            ).fetchall()
        finally:
            conn.close()
        best: dict = {}
        for username, role in rows:
            if username not in best or ROLE_RANK[role] > ROLE_RANK[best[username]]:
                best[username] = role
        return [{"username": u, "role": r} for u, r in sorted(best.items())]

    def revoke_user(self, workspace: str, username: str) -> int:
        """Delete all of a user's tokens in a workspace. Returns count removed."""
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "DELETE FROM tokens WHERE workspace = ? AND username = ?",
                    (workspace, username),
                )
                return cur.rowcount
        finally:
            conn.close()

    # ── Audit ────────────────────────────────────────────────────

    def log_audit(self, workspace: str, actor: str, action: str, detail: str = "") -> None:
        ts = time.time()
        conn = self._connect()
        try:
            # BEGIN IMMEDIATE takes the write lock before we read the previous
            # link, so concurrent request threads can't fork the hash chain.
            conn.execute("BEGIN IMMEDIATE")
            prev = conn.execute(
                "SELECT row_hash FROM audit ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev[0] if prev and prev[0] else ""
            row_hash = _audit_row_hash(prev_hash, ts, workspace, actor, action, detail)
            conn.execute(
                "INSERT INTO audit (ts, workspace, actor, action, detail, row_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, workspace, actor, action, detail, row_hash),
            )
            conn.commit()
        finally:
            conn.close()

    def verify_audit(self) -> dict:
        """Recompute the hash chain over the whole audit log. Returns
        {ok, broken_at} — broken_at is the id of the first tampered/missing row."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, ts, workspace, actor, action, detail, row_hash "
                "FROM audit ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        prev = ""
        for rid, ts, ws, actor, action, detail, stored in rows:
            expected = _audit_row_hash(prev, ts, ws, actor, action, detail or "")
            if stored != expected:
                return {"ok": False, "broken_at": rid, "count": len(rows)}
            prev = expected
        return {"ok": True, "broken_at": None, "count": len(rows)}

    def get_audit(self, workspace: str, limit: int = 100) -> List[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT ts, actor, action, detail FROM audit "
                "WHERE workspace = ? ORDER BY id DESC LIMIT ?",
                (workspace, limit),
            ).fetchall()
        finally:
            conn.close()
        return [{"ts": ts, "actor": a, "action": ac, "detail": d}
                for ts, a, ac, d in rows]

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
                "data": None if deleted else json.loads(unseal(data)),
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
                    data = {**data, "author": author or data.get("author", "")}
                    h = content_hash(data)
                    existing = conn.execute(
                        "SELECT content_hash, deleted FROM items WHERE workspace = ? AND id = ?",
                        (workspace, mid),
                    ).fetchone()
                    if existing and existing[0] == h and not existing[1]:
                        continue
                    seq = self._next_seq(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO items "
                        "(workspace, id, data, content_hash, deleted, seq) "
                        "VALUES (?, ?, ?, ?, 0, ?)",
                        (workspace, mid, seal(json.dumps(data, ensure_ascii=False)), h, seq),
                    )
                    seqs[mid] = seq

                for mid in deletions:
                    existing = conn.execute(
                        "SELECT deleted FROM items WHERE workspace = ? AND id = ?",
                        (workspace, mid),
                    ).fetchone()
                    if not existing or existing[0]:
                        continue
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
