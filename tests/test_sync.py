"""
Sync end-to-end tests (Phase 2b)
=================================

Spins up the real stdlib sync server on an ephemeral port and drives it with
the real SyncClient between two independent "developers" sharing a workspace:
push/pull propagation, tombstones, no-op pushes, and auth failures.
"""

import threading
import pytest

from rainman.core.engine import RainmanEngine
from rainman.sync import SyncClient, SyncError

# Importable via tests/conftest.py path injection.
from rainman_server.app import make_server


WS = "acme-api"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))
    monkeypatch.delenv("RAINMAN_SYNC_TOKEN", raising=False)


@pytest.fixture
def server(tmp_path):
    httpd, db = make_server("127.0.0.1", 0, str(tmp_path / "server.db"))
    db.add_token("good-token", "alice", WS)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", db
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _dev(tmp_path, name):
    proj = str(tmp_path / name)
    glob = str(tmp_path / f"{name}-global")
    engine = RainmanEngine(project_dir=proj, global_dir=glob)
    engine.store.init_project(proj)
    engine.store.init_global()
    return engine


@pytest.mark.unit
class TestSyncEndToEnd:
    def test_push_then_pull_propagates(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        b = _dev(tmp_path, "bob")

        m = a.add(content="auth.py refresh tokens via the gateway", source="cli", category="pattern")
        SyncClient(a).configure(url, WS, token="good-token")
        push_result = SyncClient(a).push()
        assert push_result["pushed"] == 1

        SyncClient(b).configure(url, WS, token="good-token")
        pulled = SyncClient(b).pull()
        assert pulled == 1
        assert any(x.id == m.id for x in b.get_all())

    def test_tombstone_propagates_delete(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        b = _dev(tmp_path, "bob")

        m = a.add(content="a shared decision about retries", source="cli", category="decision")
        SyncClient(a).configure(url, WS, token="good-token")
        SyncClient(a).sync()

        SyncClient(b).configure(url, WS, token="good-token")
        SyncClient(b).sync()
        assert any(x.id == m.id for x in b.get_all())

        # A forgets and pushes the tombstone; B pulls the delete.
        a.forget(m.id)
        SyncClient(a).sync()
        SyncClient(b).sync()
        assert all(x.id != m.id for x in b.get_all())

    def test_noop_push_sends_nothing(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        a.add(content="something to push exactly once", source="cli")
        client = SyncClient(a)
        client.configure(url, WS, token="good-token")
        assert client.push()["pushed"] == 1
        assert client.push()["pushed"] == 0  # nothing changed

    def test_bidirectional_merge(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        b = _dev(tmp_path, "bob")
        ma = a.add(content="alice's note about caching layers", source="cli")
        mb = b.add(content="bob's note about rate limiting", source="cli")

        SyncClient(a).configure(url, WS, token="good-token")
        SyncClient(b).configure(url, WS, token="good-token")
        SyncClient(a).sync()   # push A
        SyncClient(b).sync()   # pull A, push B
        SyncClient(a).sync()   # pull B

        a_ids = {x.id for x in a.get_all()}
        b_ids = {x.id for x in b.get_all()}
        assert {ma.id, mb.id} <= a_ids
        assert {ma.id, mb.id} <= b_ids

    def test_server_stamps_author(self, server, tmp_path):
        url, db = server
        a = _dev(tmp_path, "alice")
        m = a.add(content="a memory whose author the server should stamp", source="cli")
        client = SyncClient(a)
        client.configure(url, WS, token="good-token")
        client.push()
        _, changes = db.pull(WS, 0)
        rec = [c for c in changes if c["id"] == m.id][0]
        assert rec["data"]["author"] == "alice"


@pytest.mark.unit
class TestSyncAuthAndConfig:
    def test_bad_token_rejected(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        a.add(content="memory that should fail to push", source="cli")
        client = SyncClient(a)
        client.configure(url, WS, token="wrong-token")
        with pytest.raises(SyncError):
            client.push()

    def test_unconfigured_raises(self, tmp_path):
        a = _dev(tmp_path, "alice")
        with pytest.raises(SyncError):
            SyncClient(a).sync()

    def test_token_not_in_project_state(self, server, tmp_path):
        url, _ = server
        a = _dev(tmp_path, "alice")
        client = SyncClient(a)
        client.configure(url, WS, token="good-token")
        # The committable project state must not contain the token.
        import json, os
        with open(os.path.join(tmp_path, "alice", ".rainman", "sync_state.json")) as f:
            state = json.load(f)
        assert "good-token" not in json.dumps(state)
        assert "token" not in state
