"""CLI smoke tests — subprocess against a temp dir."""

import json
import os
import subprocess
import sys
import pytest


PYTHON = sys.executable


def _run_cli(args, cwd, timeout=30):
    """Run rainman CLI command via subprocess with isolated global store."""
    env = os.environ.copy()
    # Isolate from real ~/.rainman/ — use a subdir so global != project
    fakehome = os.path.join(cwd, "_fakehome")
    os.makedirs(fakehome, exist_ok=True)
    env["USERPROFILE"] = fakehome
    env["HOME"] = fakehome
    result = subprocess.run(
        [PYTHON, "-m", "rainman"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=env,
    )
    return result


@pytest.mark.unit
class TestCLISmoke:
    """End-to-end CLI: init -> add -> recall -> status -> links -> export."""

    def test_init(self, tmp_path):
        cwd = str(tmp_path)
        result = _run_cli(["init"], cwd)
        assert result.returncode == 0
        assert "Initialized" in result.stdout
        assert os.path.isdir(os.path.join(cwd, ".rainman"))
        assert os.path.exists(os.path.join(cwd, ".rainman", "memories.json"))

    def test_add(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        result = _run_cli(["add", "auth.py handles JWT token refresh",
                           "--category", "pattern", "--tag", "api"], cwd)
        assert result.returncode == 0
        assert "Added" in result.stdout
        assert "pattern" in result.stdout

    def test_recall(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "auth.py handles JWT token refresh logic",
                   "--category", "pattern"], cwd)
        result = _run_cli(["recall", "JWT token refresh"], cwd)
        assert result.returncode == 0
        assert "auth" in result.stdout

    def test_recall_empty(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        result = _run_cli(["recall", "nonexistent topic"], cwd)
        assert result.returncode == 0
        assert "No memories" in result.stdout

    def test_status(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "test memory one", "--category", "failure"], cwd)
        _run_cli(["add", "test memory two", "--category", "pattern"], cwd)
        result = _run_cli(["status"], cwd)
        assert result.returncode == 0
        assert "Total memories:" in result.stdout
        # Should show both categories
        assert "failure" in result.stdout
        assert "pattern" in result.stdout

    def test_links(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "auth module handles JWT tokens",
                   "--file", "services/auth.py"], cwd)
        result = _run_cli(["links", "auth.py"], cwd)
        assert result.returncode == 0
        assert "auth" in result.stdout.lower()

    def test_export(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "export test memory"], cwd)
        result = _run_cli(["export"], cwd)
        assert result.returncode == 0
        # Output should be valid JSON
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert "export test" in data[0]["content"]

    def test_context(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "recent context memory"], cwd)
        result = _run_cli(["context"], cwd)
        assert result.returncode == 0
        assert "context memory" in result.stdout

    def test_full_flow(self, tmp_path):
        """Full workflow: init -> add multiple -> recall -> status."""
        cwd = str(tmp_path)

        # Init
        r = _run_cli(["init"], cwd)
        assert r.returncode == 0

        # Add several memories
        _run_cli(["add", "payment service has race condition in rate limiter",
                   "--category", "failure", "--tag", "api"], cwd)
        _run_cli(["add", "auth.py handles JWT token refresh logic",
                   "--category", "pattern", "--tag", "api",
                   "--file", "services/api/auth.py"], cwd)
        _run_cli(["add", "CSS fix for dark mode sidebar", "--category", "solution"], cwd)

        # Recall — should find API memories
        r = _run_cli(["recall", "rate-limit bug"], cwd)
        assert r.returncode == 0
        assert "rate" in r.stdout.lower()
        assert "auth" in r.stdout or "race condition" in r.stdout

        # Status — should show 3 memories
        r = _run_cli(["status"], cwd)
        assert "Total memories: 3" in r.stdout

        # Links — should find auth.py
        r = _run_cli(["links", "auth.py"], cwd)
        assert r.returncode == 0
        assert "JWT" in r.stdout or "auth" in r.stdout


@pytest.mark.unit
class TestSetupWritesLocalSettings:
    """Hooks must land in the machine-local settings.local.json, never the
    committable settings.json (tool-config in git = auto-execution on clone).
    Old installs get migrated."""

    def test_setup_targets_local_and_migrates_legacy(self, tmp_path, monkeypatch):
        import json
        from rainman.cli import commands

        project = tmp_path / "proj"
        claude = project / ".claude"
        claude.mkdir(parents=True)
        # A legacy install: rainman hook + an unrelated user hook in settings.json
        legacy = {
            "hooks": {
                "SessionStart": [
                    {"matcher": "", "hooks": [
                        {"type": "command", "command": "python -m rainman.hooks.session_start"}]},
                    {"matcher": "", "hooks": [
                        {"type": "command", "command": "echo keep-me"}]},
                ]
            },
            "model": "opus",
        }
        (claude / "settings.json").write_text(json.dumps(legacy), encoding="utf-8")

        import shutil
        monkeypatch.setattr(shutil, "which", lambda *_: None)  # no claude CLI
        monkeypatch.chdir(project)
        commands.cmd_setup(host="claude")

        local = json.loads((claude / "settings.local.json").read_text(encoding="utf-8"))
        joined = json.dumps(local)
        assert "rainman.hooks.session_start" in joined
        assert "rainman.hooks.post_tool_use" in joined

        migrated = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
        mjoined = json.dumps(migrated)
        assert "rainman" not in mjoined          # stripped from committable file
        assert "keep-me" in mjoined              # unrelated hook preserved
        assert migrated["model"] == "opus"       # unrelated settings preserved
