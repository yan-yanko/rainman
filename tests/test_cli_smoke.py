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
    """End-to-end CLI: init → add → recall → status → links → export."""

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
        result = _run_cli(["add", "political_identity.py assigns party ID",
                           "--category", "pattern", "--tag", "election"], cwd)
        assert result.returncode == 0
        assert "Added" in result.stdout
        assert "pattern" in result.stdout

    def test_recall(self, tmp_path):
        cwd = str(tmp_path)
        _run_cli(["init"], cwd)
        _run_cli(["add", "political_identity.py assigns party ID using ANES data",
                   "--category", "pattern"], cwd)
        result = _run_cli(["recall", "party ID assignment"], cwd)
        assert result.returncode == 0
        assert "political_identity" in result.stdout

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
                   "--file", "engine/auth.py"], cwd)
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
        """Full workflow: init → add multiple → recall → status."""
        cwd = str(tmp_path)

        # Init
        r = _run_cli(["init"], cwd)
        assert r.returncode == 0

        # Add several memories
        _run_cli(["add", "election predictor has anti-incumbent voting bias",
                   "--category", "failure", "--tag", "election"], cwd)
        _run_cli(["add", "political_identity.py assigns party ID using ANES data",
                   "--category", "pattern", "--tag", "election",
                   "--file", "engine/election/political_identity.py"], cwd)
        _run_cli(["add", "CSS fix for dark mode sidebar", "--category", "solution"], cwd)

        # Recall — should find election memories
        r = _run_cli(["recall", "election voting bias"], cwd)
        assert r.returncode == 0
        assert "election" in r.stdout.lower()
        assert "political_identity" in r.stdout or "voting bias" in r.stdout

        # Status — should show 3 memories
        r = _run_cli(["status"], cwd)
        assert "Total memories: 3" in r.stdout

        # Links — should find political_identity.py
        r = _run_cli(["links", "political_identity.py"], cwd)
        assert r.returncode == 0
        assert "party ID" in r.stdout or "political_identity" in r.stdout
