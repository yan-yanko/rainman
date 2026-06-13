"""
Encryption-at-rest tests (server)
==================================

The confidential memory content (items.data) is AES-GCM encrypted at rest when
RAINMAN_DB_KEY is set; plaintext rows still read (backward compat); reading an
encrypted row without the key fails closed.
"""

import sqlite3
import pytest

from rainman_server.db import ServerDB
from rainman_server import crypto

KEY = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"  # 32 bytes hex
WS = "acme-api"
SECRET = "the gateway secret rotation runbook lives in vault path X"


def _memory(mid="m1"):
    return {"id": mid, "content": SECRET, "timestamp": 1.0, "importance": 0.5,
            "category": "note", "source": "cli"}


@pytest.fixture(autouse=True)
def _clear_cache():
    crypto._cache.clear()
    yield
    crypto._cache.clear()


@pytest.mark.unit
class TestEncryptionAtRest:
    def test_content_encrypted_at_rest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAINMAN_DB_KEY", KEY)
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        db.push(WS, [_memory()], [], author="alice")

        raw = sqlite3.connect(path).execute("SELECT data FROM items").fetchone()[0]
        assert raw.startswith("enc:v1:")        # sealed
        assert SECRET not in raw                # plaintext content absent from disk

    def test_pull_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAINMAN_DB_KEY", KEY)
        db = ServerDB(str(tmp_path / "s.db"))
        db.push(WS, [_memory()], [], author="alice")
        _, changes = db.pull(WS, 0)
        assert changes[0]["data"]["content"] == SECRET

    def test_disabled_when_no_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RAINMAN_DB_KEY", raising=False)
        path = str(tmp_path / "s.db")
        db = ServerDB(path)
        db.push(WS, [_memory()], [], author="alice")
        raw = sqlite3.connect(path).execute("SELECT data FROM items").fetchone()[0]
        assert not raw.startswith("enc:v1:")    # stored plaintext
        assert SECRET in raw

    def test_plaintext_rows_still_readable_with_key(self, tmp_path, monkeypatch):
        """A row written before encryption was enabled still pulls cleanly."""
        path = str(tmp_path / "s.db")
        monkeypatch.delenv("RAINMAN_DB_KEY", raising=False)
        db = ServerDB(path)
        db.push(WS, [_memory()], [], author="alice")     # plaintext
        monkeypatch.setenv("RAINMAN_DB_KEY", KEY)         # key introduced later
        crypto._cache.clear()
        _, changes = db.pull(WS, 0)
        assert changes[0]["data"]["content"] == SECRET    # legacy row reads fine

    def test_encrypted_row_without_key_fails_closed(self, tmp_path, monkeypatch):
        path = str(tmp_path / "s.db")
        monkeypatch.setenv("RAINMAN_DB_KEY", KEY)
        db = ServerDB(path)
        db.push(WS, [_memory()], [], author="alice")      # encrypted
        monkeypatch.delenv("RAINMAN_DB_KEY", raising=False)
        crypto._cache.clear()
        with pytest.raises(RuntimeError):
            db.pull(WS, 0)


@pytest.mark.unit
class TestKeyHandling:
    def test_generate_key_is_32_bytes_hex(self):
        k = crypto.generate_key()
        assert len(k) == 64 and bytes.fromhex(k)

    def test_bad_key_rejected(self, monkeypatch):
        monkeypatch.setenv("RAINMAN_DB_KEY", "tooshort")
        crypto._cache.clear()
        with pytest.raises(ValueError):
            crypto.seal("x")

    def test_base64_key_accepted(self, monkeypatch):
        import base64
        monkeypatch.setenv("RAINMAN_DB_KEY", base64.b64encode(bytes(range(32))).decode())
        crypto._cache.clear()
        sealed = crypto.seal("hello")
        assert sealed.startswith("enc:v1:")
        assert crypto.unseal(sealed) == "hello"
