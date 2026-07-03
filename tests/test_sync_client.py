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


@pytest.mark.unit
class TestPersonalSync:
    """Personal (global-layer) sync: roams ~/.rainman across machines.
    State must live in the global dir (never the repo) and only global-layer
    memories may travel."""

    def _personal(self, tmp_path):
        proj = str(tmp_path / "proj")
        engine = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / "home"))
        engine.store.init_project(proj)
        engine.store.init_global()
        return engine, SyncClient(engine, personal=True)

    def test_state_lives_in_global_dir_not_repo(self, tmp_path):
        engine, client = self._personal(tmp_path)
        client.configure(REMOTE, "me-personal", token="secret-token")
        personal_state = os.path.join(engine.store.global_dir(), "personal_sync.json")
        assert os.path.exists(personal_state)
        assert not os.path.exists(
            os.path.join(engine.store._project_dir, "personal_sync.json"))
        # And the token stays in credentials, never in state.
        with open(personal_state) as f:
            assert "secret-token" not in f.read()

    def test_push_sends_only_global_layer(self, tmp_path, monkeypatch):
        engine, client = self._personal(tmp_path)
        client.configure(REMOTE, "me-personal", token="t")
        g = engine.add(content="my personal cross-project convention", layer="global")
        engine.add(content="team project knowledge stays home", layer="project")

        sent = {}
        def fake(method, remote, path, token, body=None):
            sent["body"] = body
            return {}
        monkeypatch.setattr(client, "_request", fake)

        res = client.push()
        ids = [m["id"] for m in sent["body"]["memories"]]
        assert res["pushed"] == 1 and ids == [g.id]

    def test_pull_applies_as_global_layer(self, tmp_path, monkeypatch):
        engine, client = self._personal(tmp_path)
        client.configure(REMOTE, "me-personal", token="t")
        incoming = Memory(id="pers1", content="convention from my other laptop",
                          timestamp=time.time(), importance=0.5, category="note",
                          layer="project").to_dict()  # server data can't pick the layer

        def fake(method, remote, path, token, body=None):
            return {"cursor": 4, "changes": [
                {"id": "pers1", "data": incoming, "deleted": False, "seq": 4}]}
        monkeypatch.setattr(client, "_request", fake)

        assert client.pull() == 1
        got = next(x for x in engine.get_all() if x.id == "pers1")
        assert got.layer == "global"

    def test_team_and_personal_remotes_are_independent(self, tmp_path):
        engine, personal = self._personal(tmp_path)
        team = SyncClient(engine)
        team.configure(REMOTE, "acme-team", token="t1")
        personal.configure("http://personal.example.com", "me", token="t2")
        assert team.describe()["workspace"] == "acme-team"
        assert personal.describe()["workspace"] == "me"

    def test_personal_error_message_mentions_flag(self, tmp_path):
        _, client = self._personal(tmp_path)
        with pytest.raises(SyncError, match="--personal"):
            client.sync()
