"""MCP host registry — config shapes, merge safety, and the mcp-config command."""

import json

import pytest

from rainman.integration import hosts


@pytest.mark.unit
class TestHostRegistry:

    def test_known_hosts_cover_the_majors(self):
        keys = hosts.known_hosts()
        for h in ("claude", "cursor", "vscode", "windsurf", "cline", "zed", "continue"):
            assert h in keys

    def test_snippet_wrapper_shapes(self):
        # Most hosts use mcpServers; VS Code uses servers; Zed uses context_servers.
        assert "mcpServers" in hosts.snippet("cursor")
        assert "mcpServers" in hosts.snippet("windsurf")
        assert "servers" in hosts.snippet("vscode")
        assert "context_servers" in hosts.snippet("zed")

    def test_claude_entry_is_typed_stdio(self):
        entry = hosts.snippet("claude")["mcpServers"]["rainman"]
        assert entry["type"] == "stdio"
        assert entry["command"] == "python"
        assert entry["args"] == ["-m", "rainman", "serve"]

    def test_zed_nests_the_command(self):
        entry = hosts.snippet("zed")["context_servers"]["rainman"]
        assert entry["command"]["path"] == "python"
        assert entry["command"]["args"] == ["-m", "rainman", "serve"]

    def test_project_local_flags(self):
        assert hosts.is_project_local("cursor") is True
        assert hosts.is_project_local("vscode") is True
        assert hosts.is_project_local("windsurf") is False  # global config
        assert hosts.is_project_local("zed") is False

    def test_merge_creates_then_is_idempotent(self, tmp_path):
        path = str(tmp_path / ".cursor" / "mcp.json")
        assert "wrote" in hosts.merge_into(path, "cursor")
        data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        assert data["mcpServers"]["rainman"]["command"] == "python"
        # Second call must not duplicate.
        assert "skipped" in hosts.merge_into(path, "cursor")

    def test_merge_preserves_other_servers(self, tmp_path):
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "foo"}}}))
        hosts.merge_into(str(path), "cursor")
        data = json.loads(path.read_text())
        assert "other" in data["mcpServers"]      # untouched
        assert "rainman" in data["mcpServers"]     # added

    def test_mcp_config_command_runs(self, capsys):
        from rainman.cli.commands import cmd_mcp_config
        cmd_mcp_config(None)
        assert "MCP" in capsys.readouterr().out
        cmd_mcp_config("cursor")
        assert "rainman" in capsys.readouterr().out
        cmd_mcp_config("nonsense-host")
        assert "Unknown host" in capsys.readouterr().out
