"""
Client-side sync tests (no server)
==================================

Covers SyncClient config/state/token-safety and the push/pull apply logic by
mocking the HTTP layer. The full client<->server integration tests live in the
separate rainman-server repo (which can depend on this client).
"""

import json
import os
import time
import pytest

from rainman.core.engine import RainmanEngine
from rainman.core.models import Memory
from rainman.sync import SyncClient, SyncError

WS = "acme-api"
REMOTE = "http://sync.example.com"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))
    monkeypatch.delenv("RAINMAN_SYNC_TOKEN", raising=False)


def _client(tmp_path, name="proj"):
    proj = str(tmp_path / name)
    engine = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / f"{name}-g"))
    engine.store.init_project(proj)
    engine.store.init_global()
    return engine, SyncClient(engine)


@pytest.mark.unit
class TestConfig:
    def test_token_not_in_project_state(self, tmp_path):
        engine, client = _client(tmp_path)
        client.configure(REMOTE, WS, token="secret-token")
        state_path = os.path.join(engine.store._project_dir, "sync_state.json")
        with open(state_path) as f:
            state = json.load(f)
        assert "secret-token" not in json.dumps(state)
        assert "token" not in state
        assert state["remote"] == REMOTE and state["workspace"] == WS

    def test_token_stored_in_global_creds(self, tmp_path):
        engine, client = _client(tmp_path)
        client.configure(REMOTE, WS, token="secret-token")
        assert client.describe()["token_present"] is True

    def test_unconfigured_sync_raises(self, tmp_path):
        _, client = _client(tmp_path)
        with pytest.raises(SyncError):
            client.sync()

    def test_configured_but_no_token_raises(self, tmp_path):
        _, client = _client(tmp_path)
        client.configure(REMOTE, WS, token=None)
        with pytest.raises(SyncError):
            client.push()


@pytest.mark.unit
class TestPushPull:
    def test_push_sends_changed_and_updates_baseline(self, tmp_path, monkeypatch):
        engine, client = _client(tmp_path)
        client.configure(REMOTE, WS, token="t")
        m = engine.add(content="a memory to push to the team", source="cli")

        sent = {}
        def fake(method, remote, path, token, body=None):
            sent["body"] = body
            return {}
        monkeypatch.setattr(client, "_request", fake)

        res = client.push()
        assert res["pushed"] == 1
        assert any(mm["id"] == m.id for mm in sent["body"]["memories"])
        # Second push: nothing changed -> no-op.
        assert client.push()["pushed"] == 0

    def test_pull_applies_upsert(self, tmp_path, monkeypatch):
        engine, client = _client(tmp_path)
        client.configure(REMOTE, WS, token="t")
        incoming = Memory(id="srv1", content="teammate's memory", timestamp=time.time(),
                          importance=0.5, category="note", layer="project").to_dict()

        def fake(method, remote, path, token, body=None):
            return {"cursor": 7, "changes": [
                {"id": "srv1", "data": incoming, "deleted": False, "seq": 7}]}
        monkeypatch.setattr(client, "_request", fake)

        assert client.pull() == 1
        assert any(x.id == "srv1" for x in engine.get_all())

    def test_pull_applies_tombstone(self, tmp_path, monkeypatch):
        engine, client = _client(tmp_path)
        client.configure(REMOTE, WS, token="t")
        m = engine.add(content="memory that will be deleted remotely", source="cli")

        def fake(method, remote, path, token, body=None):
            return {"cursor": 3, "changes": [
                {"id": m.id, "data": None, "deleted": True, "seq": 3}]}
        monkeypatch.setattr(client, "_request", fake)

        client.pull()
        assert all(x.id != m.id for x in engine.get_all())
