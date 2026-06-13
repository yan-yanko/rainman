"""
Server hardening tests
======================

Bearer tokens hashed at rest (never cleartext in the DB) and tamper-evident
audit log (hash-chained, tampering detected).
"""

import sqlite3
import threading
import urllib.request
import json

import pytest

from rainman_server.db import ServerDB, token_digest
from rainman_server.app import make_server

WS = "acme-api"


@pytest.mark.unit
class TestTokenAtRest:
    def test_token_stored_hashed_not_cleartext(self, tmp_path):
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        db.add_token("super-secret-token", "alice", WS, role="admin")

        raw = sqlite3.connect(path).execute("SELECT token FROM tokens").fetchone()[0]
        assert raw != "super-secret-token"          # not cleartext
        assert raw == token_digest("super-secret-token")  # stored as digest

    def test_resolve_still_works_via_raw_token(self, tmp_path):
        db = ServerDB(str(tmp_path / "s.db"))
        db.add_token("tok-xyz", "bob", WS, role="contributor")
        assert db.resolve_token("tok-xyz") == ("bob", WS, "contributor")
        assert db.resolve_token("wrong") is None

    def test_created_token_returns_raw_stores_hash(self, tmp_path):
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        raw = db.create_token("carol", WS, "reader")
        assert db.resolve_token(raw) == ("carol", WS, "reader")
        stored = sqlite3.connect(path).execute("SELECT token FROM tokens").fetchone()[0]
        assert stored == token_digest(raw) and stored != raw

    def test_pre_hashing_db_migrates_in_place(self, tmp_path):
        """A DB with a raw token (pre-hashing) gets hashed on open; the old raw
        token still authenticates afterward."""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE tokens (token TEXT PRIMARY KEY, username TEXT, workspace TEXT);"
            "INSERT INTO tokens VALUES ('legacy-raw-token', 'dave', 'ws1');"
        )
        conn.commit(); conn.close()

        db = ServerDB(path)  # triggers migration (role col + token hashing)
        # raw value no longer at rest
        at_rest = sqlite3.connect(path).execute("SELECT token FROM tokens").fetchone()[0]
        assert at_rest == token_digest("legacy-raw-token")
        # but the previously-issued token still works
        assert db.resolve_token("legacy-raw-token") == ("dave", "ws1", "contributor")


@pytest.mark.unit
class TestAuditTamperEvidence:
    def test_clean_chain_verifies(self, tmp_path):
        db = ServerDB(str(tmp_path / "s.db"))
        for i in range(5):
            db.log_audit(WS, "alice", "push", f"accepted={i}")
        result = db.verify_audit()
        assert result["ok"] is True
        assert result["count"] == 5

    def test_tampering_is_detected(self, tmp_path):
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        for i in range(4):
            db.log_audit(WS, "alice", "pull", f"e{i}")
        # Tamper directly with a past row's detail, bypassing log_audit.
        conn = sqlite3.connect(path)
        ids = [r[0] for r in conn.execute("SELECT id FROM audit ORDER BY id")]
        conn.execute("UPDATE audit SET detail = 'forged' WHERE id = ?", (ids[1],))
        conn.commit(); conn.close()

        result = db.verify_audit()
        assert result["ok"] is False
        assert result["broken_at"] == ids[1]

    def test_deleting_a_row_is_detected(self, tmp_path):
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        for i in range(4):
            db.log_audit(WS, "alice", "pull", f"e{i}")
        conn = sqlite3.connect(path)
        ids = [r[0] for r in conn.execute("SELECT id FROM audit ORDER BY id")]
        conn.execute("DELETE FROM audit WHERE id = ?", (ids[1],))
        conn.commit(); conn.close()
        assert db.verify_audit()["ok"] is False


@pytest.mark.unit
class TestVerifyEndpoint:
    def test_admin_verify_endpoint(self, tmp_path):
        httpd, db = make_server("127.0.0.1", 0, str(tmp_path / "s.db"))
        db.add_token("admin-tok", "ada", WS, role="admin")
        db.log_audit(WS, "ada", "push", "x")
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/admin/audit/verify",
                headers={"Authorization": "Bearer admin-tok"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                body = json.loads(r.read())
            assert body["ok"] is True
        finally:
            httpd.shutdown()
            t.join(timeout=5)
