"""MCP server tests — JSON-RPC layer, input validation, happy paths."""

import json
import os
import pytest

from rainman.mcp.server import RainmanMCPServer


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Create MCP server with temp storage, isolated from real ~/.rainman/."""
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    monkeypatch.setenv("RAINMAN_PROJECT", project)
    # Isolate from real ~/.rainman/
    monkeypatch.setattr("rainman.core.store.GLOBAL_DIR", global_dir)
    s = RainmanMCPServer()
    s.engine.store.init_project(project)
    s.engine.store.init_global()
    return s


def _call(server, method, params=None, msg_id=1):
    """Send a JSON-RPC message and return response."""
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle_message(msg)


@pytest.mark.unit
class TestProtocol:
    """JSON-RPC protocol handling."""

    def test_initialize(self, server):
        resp = _call(server, "initialize")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["serverInfo"]["name"] == "rainman"
        assert "tools" in result["capabilities"]

    def test_tools_list(self, server):
        resp = _call(server, "tools/list")
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {"recall", "remember", "context", "links", "status"}

    def test_ping(self, server):
        resp = _call(server, "ping")
        assert "result" in resp

    def test_unknown_method(self, server):
        resp = _call(server, "nonexistent/method")
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_notifications_initialized_no_response(self, server):
        resp = _call(server, "notifications/initialized")
        assert resp is None


@pytest.mark.unit
class TestInputValidation:
    """Missing/empty required args return structured errors, not crashes."""

    def test_recall_missing_query(self, server):
        resp = _call(server, "tools/call", {
            "name": "recall",
            "arguments": {},
        })
        result = resp["result"]
        assert result["isError"] is True
        assert "query" in result["content"][0]["text"].lower()

    def test_recall_empty_query(self, server):
        resp = _call(server, "tools/call", {
            "name": "recall",
            "arguments": {"query": ""},
        })
        result = resp["result"]
        assert result["isError"] is True

    def test_remember_missing_content(self, server):
        resp = _call(server, "tools/call", {
            "name": "remember",
            "arguments": {},
        })
        result = resp["result"]
        assert result["isError"] is True
        assert "content" in result["content"][0]["text"].lower()

    def test_remember_empty_content(self, server):
        resp = _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": ""},
        })
        result = resp["result"]
        assert result["isError"] is True

    def test_links_missing_ref(self, server):
        resp = _call(server, "tools/call", {
            "name": "links",
            "arguments": {},
        })
        result = resp["result"]
        assert result["isError"] is True
        assert "ref" in result["content"][0]["text"].lower()

    def test_links_empty_ref(self, server):
        resp = _call(server, "tools/call", {
            "name": "links",
            "arguments": {"ref": ""},
        })
        result = resp["result"]
        assert result["isError"] is True

    def test_unknown_tool(self, server):
        resp = _call(server, "tools/call", {
            "name": "nonexistent_tool",
            "arguments": {},
        })
        result = resp["result"]
        assert result["isError"] is True
        assert "unknown" in result["content"][0]["text"].lower()

    def test_internal_error_is_sanitized(self, server):
        """An unexpected exception must not leak its message to the model."""
        secret = "boom /secret/internal/path leaked"

        def explode(*a, **k):
            raise RuntimeError(secret)

        server.engine.recall = explode
        resp = _call(server, "tools/call", {
            "name": "recall",
            "arguments": {"query": "anything"},
        })
        result = resp["result"]
        assert result["isError"] is True
        text = result["content"][0]["text"]
        assert secret not in text
        assert "internal error" in text.lower()


@pytest.mark.unit
class TestHappyPath:
    """All 5 tools work correctly with valid input."""

    def test_remember_then_recall(self, server):
        # Remember
        resp = _call(server, "tools/call", {
            "name": "remember",
            "arguments": {
                "content": "auth.py handles JWT token refresh logic",
                "category": "pattern",
                "tags": ["api"],
            },
        })
        result = resp["result"]
        assert "isError" not in result or result["isError"] is False
        assert "Remembered" in result["content"][0]["text"]

        # Recall
        resp = _call(server, "tools/call", {
            "name": "recall",
            "arguments": {"query": "JWT token refresh"},
        })
        text = resp["result"]["content"][0]["text"]
        assert "auth" in text
        assert "pattern" in text

    def test_context_empty_store(self, server):
        resp = _call(server, "tools/call", {
            "name": "context",
            "arguments": {},
        })
        text = resp["result"]["content"][0]["text"]
        assert "No memories" in text

    def test_context_with_memories(self, server):
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": "test memory for context"},
        })
        resp = _call(server, "tools/call", {
            "name": "context",
            "arguments": {"limit": 5},
        })
        text = resp["result"]["content"][0]["text"]
        assert "test memory" in text

    def test_links_tool(self, server):
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {
                "content": "auth module handles JWT",
                "file_refs": ["services/auth.py"],
            },
        })
        resp = _call(server, "tools/call", {
            "name": "links",
            "arguments": {"ref": "auth.py"},
        })
        text = resp["result"]["content"][0]["text"]
        assert "auth" in text.lower()

    def test_status_tool(self, server):
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": "bug fix for login", "category": "failure"},
        })
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": "caching pattern", "category": "pattern"},
        })
        resp = _call(server, "tools/call", {
            "name": "status",
            "arguments": {},
        })
        text = resp["result"]["content"][0]["text"]
        assert "Total memories: 2" in text

    def test_remember_global_layer(self, server):
        resp = _call(server, "tools/call", {
            "name": "remember",
            "arguments": {
                "content": "cross-project learning",
                "global": True,
            },
        })
        text = resp["result"]["content"][0]["text"]
        assert "Remembered" in text

    def test_recall_with_category_filter(self, server):
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": "auth bug report", "category": "failure"},
        })
        _call(server, "tools/call", {
            "name": "remember",
            "arguments": {"content": "auth solution found", "category": "solution"},
        })
        resp = _call(server, "tools/call", {
            "name": "recall",
            "arguments": {"query": "auth", "category": "failure"},
        })
        text = resp["result"]["content"][0]["text"]
        assert "failure" in text
        assert "solution" not in text.lower().split("failure")[0]  # solution shouldn't appear
