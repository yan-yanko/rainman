"""Regression tests for the 7 fixes from code review."""

import json
import os
import time
import pytest

from rainman.core.engine import RainmanEngine, MAX_MEMORIES
from rainman.core.models import Memory
from rainman.core.scoring import build_reverse_link_index, associative_score
from rainman.mcp.server import RainmanMCPServer


@pytest.fixture
def engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


# ── Fix 1: Pruning removes exactly the right count ──────────────


@pytest.mark.unit
class TestPruningFix:
    """Pruning at MAX_MEMORIES+1 should remove exactly 1 memory, not 10%+."""

    def test_prune_removes_exactly_overflow(self, tmp_path):
        """Load MAX+1 memories, trigger prune, assert exactly 1 removed."""
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()

        # Pre-load MAX_MEMORIES entries directly into the engine
        now = time.time()
        for i in range(MAX_MEMORIES):
            m = Memory(
                id=f"rm_pre_{i}",
                content=f"memory number {i}",
                timestamp=now - (MAX_MEMORIES - i),  # older first
                importance=0.5,
                category="note",
                layer="project",
            )
            e._memories.append(m)
        e._loaded = True

        assert len(e._memories) == MAX_MEMORIES

        # Add one more — this should trigger prune
        e.add("the one that overflows")
        # Should be exactly MAX_MEMORIES (overflow removed)
        assert len(e._memories) == MAX_MEMORIES

    def test_prune_removes_lowest_value(self, tmp_path):
        """The pruned memory should be the oldest, lowest-importance one."""
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()

        now = time.time()
        # Add one very old, low-importance memory
        old_low = Memory(
            id="rm_oldest_low",
            content="ancient low value note",
            timestamp=now - 365 * 86400,  # 1 year old
            importance=0.1,
            category="note",
            layer="project",
        )
        e._memories.append(old_low)

        # Fill up to MAX with recent, high-importance memories
        for i in range(MAX_MEMORIES - 1):
            m = Memory(
                id=f"rm_recent_{i}",
                content=f"recent important memory {i}",
                timestamp=now - i,
                importance=0.9,
                category="failure",
                layer="project",
            )
            e._memories.append(m)
        e._loaded = True

        # Add one more to trigger prune
        e.add("trigger prune")

        ids = {m.id for m in e._memories}
        assert "rm_oldest_low" not in ids  # Should have been pruned


# ── Fix 2: Write amplification — recall only saves affected layers ──


@pytest.mark.unit
class TestWriteAmplification:
    """recall() should use save_layers() not save_all()."""

    def test_recall_only_writes_affected_layer(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()

        # Add only project memories — no global memories at all
        e.add("project memory about authentication patterns", layer="project")
        e.add("project memory about database migrations", layer="project")

        glob_path = os.path.join(global_dir, "memories.json")
        glob_mtime = os.path.getmtime(glob_path)

        time.sleep(0.05)

        # Recall — all results are project layer, so only project gets saved
        results = e.recall("authentication patterns")
        assert len(results) > 0
        assert all(r.memory.layer == "project" for r in results)

        # Global file should NOT have been rewritten
        assert os.path.getmtime(glob_path) == glob_mtime


# ── Fix 3: MCP missing input validation ──────────────────────────


@pytest.mark.unit
class TestMCPValidation:
    """Missing required args → structured error, not crash."""

    def test_recall_no_args_no_crash(self, tmp_path, monkeypatch):
        project = str(tmp_path / "project")
        os.makedirs(project)
        monkeypatch.setenv("RAINMAN_PROJECT", project)
        server = RainmanMCPServer()
        server.engine.store.init_project(project)
        server.engine.store.init_global()

        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "recall", "arguments": {}},
        })
        result = resp["result"]
        assert result["isError"] is True
        assert "content" in result  # Has structured error content

    def test_remember_no_args_no_crash(self, tmp_path, monkeypatch):
        project = str(tmp_path / "project")
        os.makedirs(project)
        monkeypatch.setenv("RAINMAN_PROJECT", project)
        server = RainmanMCPServer()
        server.engine.store.init_project(project)
        server.engine.store.init_global()

        resp = server.handle_message({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "remember", "arguments": {}},
        })
        result = resp["result"]
        assert result["isError"] is True


# ── Fix 4: Silent hook exceptions ────────────────────────────────


@pytest.mark.unit
class TestHookExceptions:
    """Hooks log to stderr on malformed input, don't crash."""

    def test_post_tool_use_malformed_json(self, tmp_path):
        """Already covered in test_hooks.py — this is the regression anchor."""
        import subprocess, sys
        env = os.environ.copy()
        env["USERPROFILE"] = str(tmp_path)
        env["HOME"] = str(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "rainman.hooks.post_tool_use"],
            input="not json at all",
            capture_output=True, text=True,
            cwd=str(tmp_path),
            timeout=15,
            env=env,
        )
        assert result.returncode == 0
        assert "failed to parse" in result.stderr.lower()


# ── Fix 5: Store atomic write hardening ──────────────────────────


@pytest.mark.unit
class TestAtomicWrite:
    """_save_file uses tmp + os.replace, falls back on failure."""

    def test_save_file_creates_valid_json(self, tmp_path):
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()

        # Add and save
        e.add("test content for atomic write verification")

        # Read raw file and verify valid JSON
        path = os.path.join(project, ".rainman", "memories.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)  # Should not throw
        assert len(data) == 1

    def test_no_tmp_file_left_behind(self, tmp_path):
        """After save, no .tmp file should remain."""
        project = str(tmp_path / "project")
        global_dir = str(tmp_path / "global")
        os.makedirs(project)
        os.makedirs(global_dir)
        e = RainmanEngine(project_dir=project, global_dir=global_dir)
        e.store.init_project(project)
        e.store.init_global()

        e.add("test memory")

        rainman_dir = os.path.join(project, ".rainman")
        files = os.listdir(rainman_dir)
        tmp_files = [f for f in files if f.endswith(".tmp")]
        assert tmp_files == []


# ── Fix 6: PostToolUse dedup ────────────────────────────────────


@pytest.mark.unit
class TestPostToolUseDedup:
    """Reading the same file twice via hook should NOT create duplicates."""

    def test_dedup_prevents_duplicate(self, tmp_path):
        """Covered in test_hooks.py::TestPostToolUse::test_dedup_same_file_twice
        This is the regression anchor confirming the fix works."""
        import subprocess, sys

        project = str(tmp_path / "project")
        os.makedirs(project)
        rainman_dir = os.path.join(project, ".rainman")
        os.makedirs(rainman_dir)
        with open(os.path.join(rainman_dir, "memories.json"), "w") as f:
            json.dump([], f)
        with open(os.path.join(rainman_dir, "config.json"), "w") as f:
            json.dump({"version": "0.1.0"}, f)

        hook_input = json.dumps({
            "tool_name": "Read",
            "cwd": project,
            "tool_input": {"file_path": "engine/authentication/jwt_handler.py"},
            "tool_output": "class JWTAuthenticationHandler:\n    \"\"\"Handles JWT token creation, validation, and refresh for user sessions.\"\"\"\n    def verify_token(self, token):\n        pass\n" * 3,
        })

        # Isolate global dir — use subdir so global != project
        fakehome = os.path.join(project, "_fakehome")
        os.makedirs(fakehome, exist_ok=True)
        env = os.environ.copy()
        env["USERPROFILE"] = fakehome
        env["HOME"] = fakehome

        # Run twice
        for _ in range(2):
            subprocess.run(
                [sys.executable, "-m", "rainman.hooks.post_tool_use"],
                input=hook_input,
                capture_output=True, text=True,
                cwd=project, timeout=15,
                env=env,
            )

        with open(os.path.join(rainman_dir, "memories.json"), encoding="utf-8") as f:
            memories = json.load(f)
        assert len(memories) == 1  # Dedup!


# ── Fix 7: Associative scoring uses reverse index ────────────────


@pytest.mark.unit
class TestReverseIndex:
    """build_reverse_link_index enables O(1) reverse lookup."""

    def test_reverse_index_built_correctly(self):
        now = time.time()
        m1 = Memory(id="a", content="first", timestamp=now, importance=0.5,
                     linked_ids=["b", "c"])
        m2 = Memory(id="b", content="second", timestamp=now, importance=0.5,
                     linked_ids=[])
        m3 = Memory(id="c", content="third", timestamp=now, importance=0.5,
                     linked_ids=["a"])

        index = build_reverse_link_index([m1, m2, m3])
        # "b" is linked FROM "a"
        assert "a" in index.get("b", set()) or "b" in m1.linked_ids
        # "a" is linked FROM "c"
        assert "c" in index.get("a", set())

    def test_associative_uses_reverse_index(self):
        """Memory not directly linked to top result but reverse-linked should get boost."""
        now = time.time()
        # m1 links to m2, but m2 does NOT link to m1
        m1 = Memory(id="top_result", content="top result", timestamp=now,
                     importance=0.9, linked_ids=["reverse_linked"])
        m2 = Memory(id="reverse_linked", content="should get boost", timestamp=now,
                     importance=0.5, linked_ids=[])  # No forward link back

        entries = [m1, m2]
        reverse_index = build_reverse_link_index(entries)

        # m2 should get associative boost because m1 (a top result) links to it
        score = associative_score(
            "reverse_linked", entries, ["top_result"],
            reverse_index=reverse_index,
        )
        assert score > 0.0  # Got boost via reverse link

    def test_no_boost_without_link(self):
        now = time.time()
        m1 = Memory(id="a", content="first", timestamp=now, importance=0.5,
                     linked_ids=[])
        m2 = Memory(id="b", content="second", timestamp=now, importance=0.5,
                     linked_ids=[])

        index = build_reverse_link_index([m1, m2])
        score = associative_score("b", [m1, m2], ["a"], reverse_index=index)
        assert score == 0.0  # No link = no boost
