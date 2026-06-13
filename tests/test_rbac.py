"""
RBAC + admin tests (Phase 3)
=============================

Role enforcement (reader/contributor/admin) on the sync protocol, the admin
API (mint/list/revoke/audit), the centralized audit trail, and migration of
pre-RBAC token databases.
"""

import json
import threading
import urllib.request
import urllib.error

import pytest

from rainman.core.engine import RainmanEngine
from rainman.sync import SyncClient, SyncError

from rainman_server.app import make_server
from rainman_server.db import ServerDB

WS = "acme-api"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("RAINMAN_ORG_POLICY", str(tmp_path / "nope.json"))
    monkeypatch.delenv("RAINMAN_SYNC_TOKEN", raising=False)


@pytest.fixture
def server(tmp_path):
    httpd, db = make_server("127.0.0.1", 0, str(tmp_path / "server.db"))
    db.add_token("reader-tok", "rhea", WS, role="reader")
    db.add_token("contrib-tok", "carl", WS, role="contributor")
    db.add_token("admin-tok", "ada", WS, role="admin")
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", db
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _dev(tmp_path, name, token, url):
    proj = str(tmp_path / name)
    engine = RainmanEngine(project_dir=proj, global_dir=str(tmp_path / f"{name}-g"))
    engine.store.init_project(proj)
    engine.store.init_global()
    client = SyncClient(engine)
    client.configure(url, WS, token=token)
    return engine, client


@pytest.mark.unit
class TestRoleEnforcement:
    def test_reader_can_pull_not_push(self, server, tmp_path):
        url, _ = server
        engine, client = _dev(tmp_path, "rhea", "reader-tok", url)
        client.pull()  # allowed
        engine.add(content="reader tries to push this memory", source="cli")
        with pytest.raises(SyncError):
            client.push()

    def test_contributor_can_push(self, server, tmp_path):
        url, _ = server
        engine, client = _dev(tmp_path, "carl", "contrib-tok", url)
        engine.add(content="contributor pushes a shared memory", source="cli")
        assert client.push()["pushed"] == 1

    def test_reader_blocked_from_admin(self, server):
        url, _ = server
        status, _ = _req("GET", f"{url}/v1/admin/users", token="reader-tok")
        assert status == 403

    def test_no_token_unauthorized(self, server):
        url, _ = server
        status, _ = _req("GET", f"{url}/v1/workspaces/{WS}/pull?since=0")
        assert status == 401


@pytest.mark.unit
class TestAdminApi:
    def test_admin_lists_users(self, server):
        url, _ = server
        status, body = _req("GET", f"{url}/v1/admin/users", token="admin-tok")
        assert status == 200
        roles = {u["username"]: u["role"] for u in body["users"]}
        assert roles == {"rhea": "reader", "carl": "contributor", "ada": "admin"}

    def test_admin_mints_and_new_token_works(self, server, tmp_path):
        url, _ = server
        status, body = _req("POST", f"{url}/v1/admin/tokens", token="admin-tok",
                            body={"username": "newbie", "role": "contributor"})
        assert status == 200
        token = body["token"]
        # The freshly minted token can push.
        engine, client = _dev(tmp_path, "newbie", token, url)
        engine.add(content="newbie pushes with a freshly minted token", source="cli")
        assert client.push()["pushed"] == 1

    def test_admin_revokes_user(self, server):
        url, _ = server
        status, body = _req("POST", f"{url}/v1/admin/revoke", token="admin-tok",
                            body={"username": "carl"})
        assert status == 200 and body["revoked"] == 1
        # carl's token no longer authorizes.
        status2, _ = _req("GET", f"{url}/v1/workspaces/{WS}/pull?since=0", token="contrib-tok")
        assert status2 == 401

    def test_audit_records_actions(self, server, tmp_path):
        url, _ = server
        engine, client = _dev(tmp_path, "carl", "contrib-tok", url)
        engine.add(content="a memory to generate an audit push event", source="cli")
        client.push()
        status, body = _req("GET", f"{url}/v1/admin/audit", token="admin-tok")
        assert status == 200
        actions = {e["action"] for e in body["events"]}
        assert "push" in actions

    def test_console_served(self, server):
        url, _ = server
        status, _, html = _raw_get(f"{url}/admin")
        assert status == 200
        assert "Rainman Sync" in html


@pytest.mark.unit
class TestMigration:
    def test_pre_rbac_token_defaults_to_contributor(self, tmp_path):
        """A token DB created before the role column gets contributor on migrate."""
        import sqlite3
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE tokens (token TEXT PRIMARY KEY, username TEXT, workspace TEXT);"
            "INSERT INTO tokens VALUES ('old-tok', 'legacy', 'ws1');"
        )
        conn.commit()
        conn.close()
        db = ServerDB(path)  # triggers migration
        assert db.resolve_token("old-tok") == ("legacy", "ws1", "contributor")


def _raw_get(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.headers.get("Content-Type"), r.read().decode("utf-8")
